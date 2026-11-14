import hashlib
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.integration.routing_terrain import TerrainAccessError, load_routing_terrain
from app.analyzer.orchestration.pipeline import ANALYSIS_VERSION, AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.api.routes import analyses
from app.connectors.usgs.mola import MolaLayout
from app.schemas import BoundingBox, CreateAnalysisRequest, JobStage, LonLat, RegionOfInterest

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
_r, _c = np.indices((SMALL.height, SMALL.width))
BLOB = b"\0" * SMALL.data_offset + np.where((_r == 135) & (_c == 382), -32768, 10 * _r + 100 * _c).astype("<i2").tobytes()
MISSION = UUID("00000000-0000-0000-0000-0000000000dd")
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def make_service(tmp_path):
    deps = AnalyzerDeps(fetch_range=lambda a, b: BLOB[a:b + 1], out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9)
    svc = AnalysisService(deps, clock=lambda: NOW)
    job = svc.submit(CreateAnalysisRequest(mission_id=MISSION, objective="terrain", roi=RegionOfInterest(
        name="t", bounds=BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=14.0, north_deg=24.0), analysis_margin_m=0)))
    svc.wait_idle()
    return svc, job.id


def test_returns_verified_arrays_and_grid(tmp_path) -> None:
    svc, aid = make_service(tmp_path)
    t = load_routing_terrain(svc, aid, ANALYSIS_VERSION)
    assert t.shape == (8, 8) and t.analysis_version == ANALYSIS_VERSION and t.terrain_version == "terrain-bundle/1"
    for name, dtype in {"elevation_m": "float32", "slope_deg": "float32", "roughness_m": "float32", "valid": "bool",
                        "source_id": "uint8", "quality_flags": "uint8"}.items():
        a = getattr(t, name)
        assert a.shape == t.shape and a.dtype == np.dtype(dtype)
    assert np.array_equal(np.isfinite(t.elevation_m), t.valid)            # NaN exactly where invalid
    assert not t.valid.all() and not t.is_usable(*np.argwhere(~t.valid)[0])
    assert t.sources[0]["product_id"] == "Mars_MGS_MOLA_DEM_mosaic_global_463m" and t.limitations


def test_cell_lookup_round_trips_for_every_cell(tmp_path) -> None:
    svc, aid = make_service(tmp_path)
    t = load_routing_terrain(svc, aid, ANALYSIS_VERSION)
    for row in range(t.shape[0]):
        for col in range(t.shape[1]):
            assert t.lonlat_to_cell(t.cell_center_lonlat(row, col)) == (row, col)
    b = t.bounds
    p = LonLat(latitude_deg=(b.north_deg + b.south_deg) / 2 + 0.01, longitude_deg_east=(b.east_deg_east + b.west_deg_east) / 2 - 0.01)
    x, y = t.lonlat_to_xy(p)
    back = t.xy_to_lonlat(x, y)
    assert (back.latitude_deg, back.longitude_deg_east) == pytest.approx((p.latitude_deg, p.longitude_deg_east), abs=1e-9)


def test_points_outside_the_grid_have_no_cell(tmp_path) -> None:
    svc, aid = make_service(tmp_path)
    t = load_routing_terrain(svc, aid, ANALYSIS_VERSION)
    b = t.bounds
    assert t.lonlat_to_cell(LonLat(latitude_deg=b.north_deg + 1.0, longitude_deg_east=b.west_deg_east + 0.1)) is None
    assert t.lonlat_to_cell(LonLat(latitude_deg=b.south_deg + 0.1, longitude_deg_east=b.east_deg_east + 1.0)) is None
    assert t.lonlat_to_cell(LonLat(latitude_deg=b.north_deg - 0.1, longitude_deg_east=b.west_deg_east + 0.1)) == (0, 0)


def test_cell_geometry_matches_the_grid_metadata(tmp_path) -> None:
    svc, aid = make_service(tmp_path)
    t = load_routing_terrain(svc, aid, ANALYSIS_VERSION)
    x0, y0 = t.cell_center_xy(0, 0)
    x1, y1 = t.cell_center_xy(1, 1)
    assert x1 - x0 == pytest.approx(t.grid.pixel_size_x_m) and y0 - y1 == pytest.approx(t.grid.pixel_size_y_m)


def test_error_codes_distinguish_the_failure(tmp_path) -> None:
    svc, aid = make_service(tmp_path)
    with pytest.raises(TerrainAccessError) as e:
        load_routing_terrain(svc, uuid4(), ANALYSIS_VERSION)
    assert e.value.code == "not_found"
    with pytest.raises(TerrainAccessError) as e:
        load_routing_terrain(svc, aid, "analysis/999")
    assert e.value.code == "version_mismatch" and "analysis/1" in str(e.value)
    pending = SimpleNamespace(get_job=lambda i: SimpleNamespace(stage=JobStage.terrain), get_result=lambda i: None, load_terrain=lambda i: None)
    with pytest.raises(TerrainAccessError) as e:
        load_routing_terrain(pending, aid, ANALYSIS_VERSION)
    assert e.value.code == "not_ready"
    npz = tmp_path / str(aid) / "terrain.npz"
    npz.write_bytes(npz.read_bytes() + b"x")                               # corrupt after the fact
    with pytest.raises(TerrainAccessError) as e:
        load_routing_terrain(svc, aid, ANALYSIS_VERSION)
    assert e.value.code == "unavailable"


def test_http_download_serves_the_verified_file(tmp_path) -> None:
    svc, aid = make_service(tmp_path)
    app = FastAPI()
    app.include_router(analyses.router, prefix="/api/v1")
    app.dependency_overrides[analyses.get_service] = lambda: svc
    c = TestClient(app)
    ok = c.get(f"/api/v1/analyses/{aid}/terrain.npz", params={"analysis_version": ANALYSIS_VERSION})
    assert ok.status_code == 200
    assert ok.headers["x-terrain-sha256"] == hashlib.sha256(ok.content).hexdigest()
    assert ok.headers["x-analysis-version"] == ANALYSIS_VERSION
    arrays = np.load(io.BytesIO(ok.content))
    assert set(arrays.files) == {"elevation_m", "slope_deg", "roughness_m", "valid", "source_id", "quality_flags"}
    wrong = c.get(f"/api/v1/analyses/{aid}/terrain.npz", params={"analysis_version": "analysis/2"})
    assert wrong.status_code == 409 and wrong.json()["detail"]["error_code"] == "version_mismatch"
    assert c.get(f"/api/v1/analyses/{uuid4()}/terrain.npz", params={"analysis_version": ANALYSIS_VERSION}).status_code == 404
    assert c.get(f"/api/v1/analyses/{aid}/terrain.npz").status_code == 422
