import threading
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.api.routes import analyses
from app.connectors.usgs.mola import MolaLayout
from app.schemas import BoundingBox, CreateAnalysisRequest, JobStage, RegionOfInterest

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
_r, _c = np.indices((SMALL.height, SMALL.width))
BLOB = b"\0" * SMALL.data_offset + (10 * _r + 100 * _c).astype("<i2").tobytes()
MISSION = UUID("00000000-0000-0000-0000-000000000abc")
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def request(east=14.0):
    return CreateAnalysisRequest(mission_id=MISSION, objective="terrain", roi=RegionOfInterest(
        name="t", bounds=BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=east, north_deg=24.0), analysis_margin_m=0))


class Gate:
    """A fetcher that holds the worker inside the download stage until released."""

    def __init__(self) -> None:
        self.entered, self.release, self.calls = threading.Event(), threading.Event(), 0
        self.lengths: set[int] = set()          # distinct request sizes: one per analysis window (rows are fetched concurrently)

    def __call__(self, a, b):
        self.calls += 1
        self.lengths.add(b - a + 1)
        self.entered.set()
        assert self.release.wait(10), "test gate was never released"
        return BLOB[a:b + 1]


def service(tmp_path, gate=None):
    fetch = gate or (lambda a, b: BLOB[a:b + 1])
    return AnalysisService(AnalyzerDeps(fetch_range=fetch, out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9), clock=lambda: NOW)


def test_cancelling_a_running_job_stops_it_and_removes_partial_files(tmp_path) -> None:
    gate = Gate()
    svc = service(tmp_path, gate)
    job = svc.submit(request())
    assert gate.entered.wait(5)                                     # the worker is inside the download stage
    cancelled = svc.cancel(job.id)
    assert cancelled.stage == JobStage.cancelled
    gate.release.set()
    svc.wait_idle()
    final = svc.get_job(job.id)
    assert final.stage == JobStage.cancelled and final.error_code is None
    assert not any((tmp_path / str(job.id) / n).exists() for n in ("terrain.npz", "terrain.manifest.json", "result.json"))
    assert svc.get_result(job.id) is None and svc.load_terrain(job.id) is None


def test_a_queued_job_that_is_cancelled_never_runs(tmp_path) -> None:
    gate = Gate()
    svc = service(tmp_path, gate)
    first = svc.submit(request(east=14.0))
    assert gate.entered.wait(5)
    second = svc.submit(request(east=13.0))                        # waits behind the first
    assert svc.cancel(second.id).stage == JobStage.cancelled
    gate.release.set()
    svc.wait_idle()
    assert svc.get_job(first.id).stage == JobStage.completed
    assert svc.get_job(second.id).stage == JobStage.cancelled and len(gate.lengths) == 1      # only the first job fetched anything (its rows share one request size)


def test_finished_and_unknown_jobs_cannot_be_cancelled(tmp_path) -> None:
    svc = service(tmp_path)
    job = svc.submit(request())
    svc.wait_idle()
    assert svc.cancel(job.id).stage == JobStage.completed          # unchanged
    assert svc.cancel(uuid4()) is None


def test_a_cancelled_request_can_be_submitted_again(tmp_path) -> None:
    gate = Gate()
    svc = service(tmp_path, gate)
    first = svc.submit(request())
    assert gate.entered.wait(5)
    svc.cancel(first.id)
    gate.release.set()
    svc.wait_idle()
    again = svc.submit(request())
    svc.wait_idle()
    assert again.id != first.id and svc.get_job(again.id).stage == JobStage.completed


def test_cancelled_state_survives_a_restart(tmp_path) -> None:
    gate = Gate()
    svc = service(tmp_path, gate)
    job = svc.submit(request())
    assert gate.entered.wait(5)
    svc.cancel(job.id)
    gate.release.set()
    svc.wait_idle()
    restarted = service(tmp_path)
    assert restarted.get_job(job.id).stage == JobStage.cancelled and restarted.get_job(job.id).error_code is None


def test_http_cancel_endpoint(tmp_path) -> None:
    gate = Gate()
    svc = service(tmp_path, gate)
    app = FastAPI()
    app.include_router(analyses.router, prefix="/api/v1")
    app.dependency_overrides[analyses.get_service] = lambda: svc
    c = TestClient(app)
    job_id = c.post("/api/v1/analyses", json=request().model_dump(mode="json")).json()["id"]
    assert gate.entered.wait(5)
    ok = c.post(f"/api/v1/analyses/{job_id}/cancel")
    assert ok.status_code == 200 and ok.json()["stage"] == "cancelled"
    assert c.post(f"/api/v1/analyses/{job_id}/cancel").status_code == 409          # already finished
    assert c.post(f"/api/v1/analyses/{uuid4()}/cancel").status_code == 404
    conflict = c.get(f"/api/v1/analyses/{job_id}/result")
    assert conflict.status_code == 409 and conflict.json()["detail"]["stage"] == "cancelled"
    gate.release.set()
    svc.wait_idle()
