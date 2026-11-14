"""Analysis job service.

* One heavy analysis at a time (a single worker thread keeps CPU work off the event loop).
* Equivalent requests share one job (same region, objective and version).
* Job state and results are written atomically to ``<out_dir>/<id>/`` so they survive a restart; a job
  that was queued or running when the process stopped is recorded as failed with code ``interrupted``.
* Progress is stage-based: it moves only when the pipeline actually enters a stage.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from app.analyzer.preprocessing.terrain_bundle import TerrainBundleError, TerrainManifest, load_terrain_bundle
from app.analyzer.publishing.science_layer import load_science_layer
from app.analyzer.validation.cache_keys import analysis_result_key, stable_hash
from app.schemas import AnalysisJob, CreateAnalysisRequest, JobStage, RegionalAnalysisResult

from .pipeline import ANALYSIS_VERSION, AnalysisError, AnalyzerDeps, run_region_analysis

TERMINAL = {JobStage.completed, JobStage.failed, JobStage.cancelled}
PARTIAL_FILES = ("terrain.npz", "terrain.manifest.json", "science.npz", "science.json", "result.json")


class _Cancelled(Exception):
    """Raised inside the worker at a stage boundary once the job has been cancelled."""


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class AnalysisService:
    def __init__(self, deps: AnalyzerDeps, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._deps, self._clock = deps, clock
        self._lock = threading.Lock()
        self._jobs: dict[UUID, AnalysisJob] = {}
        self._by_key: dict[str, UUID] = {}
        self._cancelled: set[UUID] = set()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._recover()

    # -- persistence -----------------------------------------------------------------------------
    def _job_path(self, job_id: UUID) -> Path:
        return self._deps.out_dir / str(job_id) / "job.json"

    def _save_job(self, job: AnalysisJob, key: str | None = None) -> None:
        _write_atomic(self._job_path(job.id), job.model_dump_json())
        if key:
            _write_atomic(self._deps.out_dir / str(job.id) / "key.txt", key)

    def _recover(self) -> None:
        if not self._deps.out_dir.is_dir():
            return
        for folder in sorted(self._deps.out_dir.iterdir()):
            path = folder / "job.json"
            if not path.is_file():
                continue
            try:
                job = AnalysisJob.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if job.stage not in TERMINAL:
                job = job.model_copy(update={
                    "stage": JobStage.failed, "error_code": "interrupted", "updated_at": self._clock(),
                    "message": "The service restarted while this analysis was running; submit it again.",
                })
                self._save_job(job)
            self._jobs[job.id] = job
            key_file = folder / "key.txt"
            if job.stage == JobStage.completed and key_file.is_file():
                self._by_key[key_file.read_text(encoding="utf-8")] = job.id

    # -- public API ------------------------------------------------------------------------------
    @staticmethod
    def request_key(req: CreateAnalysisRequest) -> str:
        processed = stable_hash({"bounds": req.roi.bounds.model_dump(), "margin_m": req.roi.analysis_margin_m, "version": ANALYSIS_VERSION})
        return analysis_result_key(processed, req.objective, {"mission_id": str(req.mission_id)})

    def submit(self, req: CreateAnalysisRequest) -> AnalysisJob:
        key = self.request_key(req)
        with self._lock:
            existing = self._by_key.get(key)
            if existing is not None and self._jobs[existing].stage not in (JobStage.failed, JobStage.cancelled):
                return self._jobs[existing]
            now = self._clock()
            job = AnalysisJob(id=uuid4(), mission_id=req.mission_id, stage=JobStage.queued, progress_percent=0,
                              message="Queued", created_at=now, updated_at=now)
            self._jobs[job.id] = job
            self._by_key[key] = job.id
            self._save_job(job, key)
        self._pool.submit(self._run, job.id, req, key)
        return job

    def get_job(self, job_id: UUID) -> AnalysisJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest_for_mission(self, mission_id: UUID, completed_only: bool = False) -> AnalysisJob | None:
        """Most recently created analysis for a mission (optionally only finished ones)."""
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.mission_id == mission_id and (not completed_only or j.stage == JobStage.completed)]
        return max(jobs, key=lambda j: j.created_at, default=None)

    def get_result(self, job_id: UUID) -> RegionalAnalysisResult | None:
        path = self._deps.out_dir / str(job_id) / "result.json"
        job = self.get_job(job_id)
        if job is None or job.stage != JobStage.completed or not path.is_file():
            return None
        return RegionalAnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))

    def load_terrain(self, job_id: UUID):
        """Verified terrain arrays of a completed analysis, or None (unknown, unfinished, missing or corrupt)."""
        job = self.get_job(job_id)
        path = self._deps.out_dir / str(job_id) / "terrain.manifest.json"
        if job is None or job.stage != JobStage.completed or not path.is_file():
            return None
        try:
            return load_terrain_bundle(path)
        except (TerrainBundleError, ValueError):
            return None

    def load_science(self, job_id: UUID):
        job = self.get_job(job_id)
        if job is None or job.stage != JobStage.completed:
            return None
        return load_science_layer(self._deps.out_dir / str(job_id))

    def terrain_file(self, job_id: UUID) -> Path:
        return self._deps.out_dir / str(job_id) / "terrain.npz"

    def cancel(self, job_id: UUID) -> AnalysisJob | None:
        """Cancel a queued or running analysis; a finished one is returned unchanged. None if unknown.

        A running job stops at its next stage boundary (a single network read is not interrupted) and its
        partial artifacts are removed."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.stage in TERMINAL:
                return job
            self._cancelled.add(job_id)
            job = job.model_copy(update={"stage": JobStage.cancelled, "message": "Cancelled by request", "updated_at": self._clock()})
            self._jobs[job_id] = job
        self._save_job(job)
        self._discard_partial(job_id)
        return job

    def _discard_partial(self, job_id: UUID) -> None:
        for name in PARTIAL_FILES:
            (self._deps.out_dir / str(job_id) / name).unlink(missing_ok=True)

    def wait_idle(self) -> None:
        """Block until queued work finishes (used by tests and graceful shutdown)."""
        self._pool.submit(lambda: None).result()

    # -- worker ----------------------------------------------------------------------------------
    def _update(self, job_id: UUID, **changes: object) -> None:
        with self._lock:
            current = self._jobs[job_id]
            if current.stage == JobStage.cancelled:
                return                                   # a cancelled job never changes state again
            job = current.model_copy(update={**changes, "updated_at": self._clock()})
            self._jobs[job_id] = job
        self._save_job(job)

    def _run(self, job_id: UUID, req: CreateAnalysisRequest, key: str) -> None:
        def progress(stage: JobStage, percent: int, message: str) -> None:
            if job_id in self._cancelled:
                raise _Cancelled()
            self._update(job_id, stage=stage, progress_percent=percent, message=message)
        if job_id in self._cancelled:
            return
        try:
            result = run_region_analysis(job_id, req, self._deps, progress, self._clock())
            if job_id in self._cancelled:
                raise _Cancelled()
            _write_atomic(self._deps.out_dir / str(job_id) / "result.json", result.model_dump_json())
            self._update(job_id, stage=JobStage.completed, progress_percent=100, message="Analysis complete", warnings=result.warnings)
        except _Cancelled:
            self._discard_partial(job_id)
        except AnalysisError as exc:
            self._update(job_id, stage=JobStage.failed, error_code=exc.code, message=str(exc))
        except Exception as exc:  # unexpected: report without leaking internals, keep the worker alive
            self._update(job_id, stage=JobStage.failed, error_code="internal_error", message=f"Unexpected {type(exc).__name__} during analysis")
