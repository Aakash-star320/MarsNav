from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.analyzer.publishing.map_display import render_hazard_png
from app.api.routes import analyses
from app.schemas import BoundingBox, CreateAnalysisRequest, RegionOfInterest

from .test_map_display import AID, SMALL, blob, bundle, decode_png


def test_hazard_layer_marks_only_cells_steeper_than_the_limit(tmp_path) -> None:
    _, arrays = bundle(tmp_path, fn=lambda r, c: 100 * c)       # a steady ramp of about 6.2 degrees
    strict = decode_png(render_hazard_png(arrays, 4.0))
    lenient = decode_png(render_hazard_png(arrays, 7.0))
    assert (strict[..., 3] > 0).all()                  # every defined cell is steeper than 4 degrees
    assert (lenient[..., 3] == 0).all()                # none is steeper than 7 degrees; unknown cells are never marked


def test_hazard_endpoint_validates_the_limit(tmp_path) -> None:
    data = blob(lambda r, c: 100 * c)
    deps = AnalyzerDeps(fetch_range=lambda a, b: data[a:b + 1], out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9)
    svc = AnalysisService(deps)
    app = FastAPI()
    app.include_router(analyses.router, prefix="/api/v1")
    app.dependency_overrides[analyses.get_service] = lambda: svc
    c = TestClient(app)
    req = CreateAnalysisRequest(mission_id=AID, objective="terrain", roi=RegionOfInterest(
        name="t", bounds=BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=14.0, north_deg=24.0), analysis_margin_m=0))
    job_id = c.post("/api/v1/analyses", json=req.model_dump(mode="json")).json()["id"]
    svc.wait_idle()
    ok = c.get(f"/api/v1/analyses/{job_id}/layers/hazard.png", params={"slope_limit_deg": 3})
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png" and "hazard-3" in ok.headers["etag"]
    assert c.get(f"/api/v1/analyses/{job_id}/layers/hazard.png", params={"slope_limit_deg": 0}).status_code == 422
