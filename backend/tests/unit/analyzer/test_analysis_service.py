from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.orchestration.pipeline import AnalyzerDeps, run_region_analysis
from app.analyzer.orchestration.service import AnalysisService
from app.api.routes import analyses
from app.connectors.usgs.mola import MolaError, MolaLayout, dataset_record, pixel_window
from app.schemas import AnalysisJob, BoundingBox, CreateAnalysisRequest, JobStage, RegionOfInterest

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
_rows, _cols = np.indices((SMALL.height, SMALL.width))
BLOB = b"\0" * SMALL.data_offset + (100 * _cols).astype("<i2").tobytes()
MISSION = UUID("00000000-0000-0000-0000-0000000000bb")
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def request(west=10.0, east=14.0, objective="find hydrated minerals", margin=0.0):
    roi = RegionOfInterest(name="test", bounds=BoundingBox(west_deg_east=west, south_deg=20.0, east_deg_east=east, north_deg=24.0),
                           analysis_margin_m=margin)
    return CreateAnalysisRequest(mission_id=MISSION, roi=roi, objective=objective)


def deps(tmp_path, fetch=None, **kw):
    return AnalyzerDeps(fetch_range=fetch or (lambda a, b: BLOB[a:b + 1]), out_dir=tmp_path, mola_layout=SMALL,
                        max_area_km2=1e9, **kw)


def client(service):
    app = FastAPI()
    app.include_router(analyses.router, prefix="/api/v1")
    app.dependency_overrides[analyses.get_service] = lambda: service
    return TestClient(app)


def test_pipeline_reports_real_stage_transitions_in_order(tmp_path) -> None:
    seen = []
    result = run_region_analysis(uuid4(), request(), deps(tmp_path), lambda s, p, m: seen.append((s, p)), NOW)
    assert [s for s, _ in seen] == [JobStage.discovery, JobStage.selection, JobStage.downloading, JobStage.preprocessing, JobStage.terrain]
    assert [p for _, p in seen] == sorted(p for _, p in seen)
    assert [layer.kind for layer in result.layers] == ["elevation", "slope", "roughness", "validity", "source"]
    assert result.science_targets == []
    assert any("not interpreted" in w for w in result.warnings) and any("463 m" in w for w in result.warnings)
    assert result.projection_wkt == result.grid.crs_wkt and result.datasets[0].product_id.startswith("Mars_MGS_MOLA")


def test_http_flow_create_poll_result(tmp_path) -> None:
    svc = AnalysisService(deps(tmp_path), clock=lambda: NOW)
    c = client(svc)
    r = c.post("/api/v1/analyses", json=request().model_dump(mode="json"))
    assert r.status_code == 202
    job_id = r.json()["id"]
    svc.wait_idle()
    job = c.get(f"/api/v1/analyses/{job_id}").json()
    assert job["stage"] == "completed" and job["progress_percent"] == 100
    res = c.get(f"/api/v1/analyses/{job_id}/result")
    assert res.status_code == 200 and res.json()["id"] == job_id
    assert (tmp_path / job_id / "terrain.npz").is_file() and (tmp_path / job_id / "result.json").is_file()


def test_equivalent_requests_share_one_job(tmp_path) -> None:
    svc = AnalysisService(deps(tmp_path))
    a, b = svc.submit(request()), svc.submit(request())
    svc.wait_idle()
    assert a.id == b.id
    assert svc.submit(request(east=13.0)).id != a.id


def test_unknown_and_invalid_requests(tmp_path) -> None:
    svc = AnalysisService(deps(tmp_path))
    c = client(svc)
    assert c.get(f"/api/v1/analyses/{uuid4()}").status_code == 404
    assert c.get(f"/api/v1/analyses/{uuid4()}/result").status_code == 404
    assert c.post("/api/v1/analyses", json={"mission_id": str(MISSION)}).status_code == 422


def test_area_limit_fails_job_with_clear_code(tmp_path) -> None:
    svc = AnalysisService(AnalyzerDeps(fetch_range=lambda a, b: b"", out_dir=tmp_path, mola_layout=SMALL, max_area_km2=25))
    c = client(svc)
    job_id = c.post("/api/v1/analyses", json=request().model_dump(mode="json")).json()["id"]
    svc.wait_idle()
    job = c.get(f"/api/v1/analyses/{job_id}").json()
    assert job["stage"] == "failed" and job["error_code"] == "area_limit"
    conflict = c.get(f"/api/v1/analyses/{job_id}/result")
    assert conflict.status_code == 409 and conflict.json()["detail"]["error_code"] == "area_limit"


def test_source_failure_is_reported_and_worker_survives(tmp_path) -> None:
    def width(east: float) -> int:                      # bytes per row request for a window ending at ``east``
        _, _, c0, c1 = pixel_window(BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=east, north_deg=24.0), SMALL, 1)
        return (c1 - c0) * 2

    def flaky(a, b):                                    # rows are fetched concurrently, so fail by window size, not call order
        n = b - a + 1
        if n == width(14.0):
            raise MolaError("fetch_failed", "server unreachable")
        if n == width(13.0):
            raise RuntimeError("secret internal detail")
        return BLOB[a:b + 1]
    svc = AnalysisService(deps(tmp_path, fetch=flaky))
    j1, j2, j3 = svc.submit(request(east=14.0)), svc.submit(request(east=13.0)), svc.submit(request(east=12.0))
    svc.wait_idle()
    assert svc.get_job(j1.id).error_code == "elevation_fetch_failed"
    assert svc.get_job(j2.id).error_code == "internal_error"
    assert "secret internal detail" not in svc.get_job(j2.id).message
    assert svc.get_job(j3.id).stage == JobStage.completed       # the worker kept going


def test_failed_job_can_be_resubmitted(tmp_path) -> None:
    state = {"fail": True}

    def fetch(a, b):
        if state["fail"]:
            raise MolaError("fetch_failed", "down")
        return BLOB[a:b + 1]
    svc = AnalysisService(deps(tmp_path, fetch=fetch))
    first = svc.submit(request())
    svc.wait_idle()
    assert svc.get_job(first.id).stage == JobStage.failed
    state["fail"] = False
    second = svc.submit(request())
    svc.wait_idle()
    assert second.id != first.id and svc.get_job(second.id).stage == JobStage.completed


def test_no_elevation_coverage_is_unavailable_not_invented(tmp_path) -> None:
    base = dataset_record(SMALL)
    far = base.model_copy(update={"coverage": base.coverage.model_copy(
        update={"footprint": BoundingBox(west_deg_east=100, south_deg=-10, east_deg_east=110, north_deg=10)})})
    svc = AnalysisService(deps(tmp_path, catalog=lambda: [far]))
    job = svc.submit(request())
    svc.wait_idle()
    assert svc.get_job(job.id).error_code == "no_elevation_data"


def test_completed_work_and_interrupted_jobs_survive_restart(tmp_path) -> None:
    svc = AnalysisService(deps(tmp_path), clock=lambda: NOW)
    done = svc.submit(request())
    svc.wait_idle()
    stuck = AnalysisJob(id=uuid4(), mission_id=MISSION, stage=JobStage.terrain, progress_percent=80, message="x",
                        created_at=NOW, updated_at=NOW)
    (tmp_path / str(stuck.id)).mkdir()
    (tmp_path / str(stuck.id) / "job.json").write_text(stuck.model_dump_json())
    restarted = AnalysisService(deps(tmp_path), clock=lambda: NOW)
    assert restarted.get_job(done.id).stage == JobStage.completed and restarted.get_result(done.id) is not None
    assert restarted.get_job(stuck.id).stage == JobStage.failed and restarted.get_job(stuck.id).error_code == "interrupted"
    assert restarted.submit(request()).id == done.id          # de-duplication survives the restart


def test_margin_grows_the_region(tmp_path) -> None:
    small = run_region_analysis(uuid4(), request(margin=0.0), deps(tmp_path / "a"), lambda *a: None, NOW)
    big = run_region_analysis(uuid4(), request(margin=100_000.0), deps(tmp_path / "b"), lambda *a: None, NOW)

    def width(res):
        b = res.layers[0].bounds
        return b.east_deg_east - b.west_deg_east
    assert width(big) > width(small)
