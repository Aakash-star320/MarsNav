import json
import math
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.analyzer.preprocessing.terrain_bundle import build_terrain_bundle, load_terrain_bundle
from app.analyzer.publishing.map_display import build_map_package, colorize, display_arrays, png_bytes
from app.api.routes import analyses
from app.connectors.usgs.mola import MolaLayout, dataset_record, read_window
from app.schemas import BoundingBox, CreateAnalysisRequest, RegionOfInterest

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
AID = UUID("00000000-0000-0000-0000-0000000000cc")
SAMPLE_DEM = Path(__file__).parents[3].parent / "data" / "sample" / "dem.synthetic.json"


def blob(fn):
    rows, cols = np.indices((SMALL.height, SMALL.width))
    return b"\0" * SMALL.data_offset + fn(rows, cols).astype("<i2").tobytes()


def bundle(tmp_path, fn=lambda r, c: 10 * r + c % 5, box=(10.0, 20.0, 14.0, 24.0)):
    data = blob(fn)
    aoi = BoundingBox(west_deg_east=box[0], south_deg=box[1], east_deg_east=box[2], north_deg=box[3])
    win = read_window(aoi, lambda a, b: data[a:b + 1], SMALL, halo_px=1)
    build_terrain_bundle(win, dataset_record(SMALL), AID, tmp_path, generated_at=datetime(2026, 11, 14, tzinfo=timezone.utc))
    return load_terrain_bundle(tmp_path / str(AID) / "terrain.manifest.json")


def decode_png(data: bytes) -> np.ndarray:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n, tag = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        assert zlib.crc32(tag + body) & 0xFFFFFFFF == struct.unpack(">I", data[pos + 8 + n:pos + 12 + n])[0]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = [np.frombuffer(raw[i * (w * 4 + 1) + 1:(i + 1) * (w * 4 + 1)], dtype=np.uint8).reshape(w, 4) for i in range(h)]
    return np.stack(rows)


def test_png_round_trip_and_transparency_for_invalid_cells() -> None:
    values = np.array([[0.0, 5.0], [10.0, np.nan]])
    valid = np.isfinite(values)
    rgba = colorize(values, valid, 0.0, 10.0, ["#000000", "#ffffff"])
    back = decode_png(png_bytes(rgba))
    assert np.array_equal(back, rgba)
    assert back[1, 1, 3] == 0 and back[0, 0, 3] == 255                     # invalid is transparent, not zero-coloured
    assert tuple(back[0, 0, :3]) == (0, 0, 0) and tuple(back[1, 0, :3]) == (255, 255, 255)


def test_package_matches_the_map_modules_dem_shape(tmp_path) -> None:
    manifest, arrays = bundle(tmp_path)
    pkg = build_map_package(manifest, arrays, lambda kind: f"http://x/{kind}.png")
    fixture = json.loads(SAMPLE_DEM.read_text(encoding="utf-8"))
    assert set(pkg.dem.model_dump(mode="json")) == set(fixture)           # same fields the 3D view reads
    assert set(pkg.dem.projection.model_dump()) == set(fixture["projection"])
    assert (pkg.dem.width, pkg.dem.height) == (8, 8) and len(pkg.dem.values) == 64


def test_every_layer_has_exactly_the_dem_bounds(tmp_path) -> None:
    manifest, arrays = bundle(tmp_path)
    pkg = build_map_package(manifest, arrays, lambda kind: f"http://x/{kind}.png")
    assert [e.layer.kind for e in pkg.layers] == ["elevation", "slope", "roughness"]
    for e in pkg.layers:
        assert e.layer.bounds == pkg.dem.bounds                           # the 3D view requires equality (1e-8)
        assert e.projection == "MARS:CANONICAL_ANGULAR" and e.format == "image" and not e.synthetic
        assert e.layer.uri == f"http://x/{e.layer.kind}.png" and "MOLA" in e.legend


def test_dem_affine_and_bounds_agree_under_the_documented_projection(tmp_path) -> None:
    manifest, arrays = bundle(tmp_path)
    dem = build_map_package(manifest, arrays, lambda k: "http://x").dem
    p, a = dem.projection, dem.affine
    lat = lambda y: p.latitude_origin_deg + math.degrees(y / p.radius_m)
    lon = lambda x: p.longitude_origin_deg_east + math.degrees(x / (p.radius_m * math.cos(math.radians(p.latitude_origin_deg))))
    assert lon(a[0]) == pytest.approx(dem.bounds.west_deg_east, abs=1e-9)
    assert lat(a[3]) == pytest.approx(dem.bounds.north_deg, abs=1e-9)
    assert lon(a[0] + (dem.width - 1) * a[1]) == pytest.approx(dem.bounds.east_deg_east, abs=1e-9)
    assert lat(a[3] + (dem.height - 1) * a[5]) == pytest.approx(dem.bounds.south_deg, abs=1e-9)
    assert a[5] < 0 < a[1]                                                # rows run north to south


def test_missing_cells_are_null_in_the_dem_and_layers_keep_coverage(tmp_path) -> None:
    manifest, arrays = bundle(tmp_path, fn=lambda r, c: np.where((r == 135) & (c == 382), -32768, 50))
    pkg = build_map_package(manifest, arrays, lambda k: "http://x")
    assert pkg.dem.values.count(None) == 1
    elevation = pkg.layers[0]
    assert elevation.coverage == "partial" and elevation.layer.valid_percent < 100


def test_large_grids_are_decimated_and_stay_consistent() -> None:
    rows, cols = 600, 500
    arrays = {n: np.zeros((rows, cols), dtype=t) for n, t in
              {"elevation_m": "f4", "slope_deg": "f4", "roughness_m": "f4", "valid": "?", "source_id": "u1", "quality_flags": "u1"}.items()}
    disp, k = display_arrays(arrays, max_dim=257)
    assert k == 3 and disp["valid"].shape == ((rows - 1) // 3 + 1, (cols - 1) // 3 + 1)
    assert max(disp["valid"].shape) <= 257


def test_http_flow_serves_package_and_png(tmp_path) -> None:
    data = blob(lambda r, c: 10 * r + c % 5)
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
    pkg = c.get(f"/api/v1/analyses/{job_id}/map")
    assert pkg.status_code == 200
    body = pkg.json()
    url = body["layers"][0]["layer"]["uri"]
    assert url.startswith("http://testserver/api/v1/analyses/") and url.endswith("/layers/elevation.png")
    png = c.get(url.replace("http://testserver", ""))
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    img = decode_png(png.content)
    assert img.shape[:2] == (body["dem"]["height"], body["dem"]["width"])
    assert c.get(f"/api/v1/analyses/{job_id}/layers/other.png").status_code == 422
    assert c.get("/api/v1/analyses/00000000-0000-0000-0000-000000000001/map").status_code == 404


def test_statistics_describe_valid_cells_and_state_their_denominator(tmp_path) -> None:
    manifest, arrays = bundle(tmp_path, fn=lambda r, c: np.where((r == 135) & (c == 382), -32768, 100 * c))
    from app.analyzer.publishing.statistics import compute_statistics

    st = compute_statistics(manifest, arrays, slope_limit_deg=5.0)
    assert st.cells_total == 64 and st.cells_valid == 63 and st.valid_percent == pytest.approx(100 * 63 / 64)
    g = manifest.grid
    assert st.area_km2 == pytest.approx(8 * g.pixel_size_x_m * 8 * g.pixel_size_y_m / 1e6)
    assert st.elevation_min_m is not None and st.elevation_max_m > st.elevation_min_m
    assert st.slope_denominator_cells <= st.cells_valid                      # unknown cells never enter the denominator
    assert st.slope_exceedance_fraction == pytest.approx(st.slope_exceedance_cells / st.slope_denominator_cells)
    lenient = compute_statistics(manifest, arrays, slope_limit_deg=45.0)
    assert lenient.slope_exceedance_cells <= st.slope_exceedance_cells
    assert st.science_candidates == 0 and any("not a safety assessment" in n for n in st.notes)


def test_map_endpoint_includes_statistics_and_honours_the_slope_limit(tmp_path) -> None:
    data = blob(lambda r, c: 10 * r + c % 5)
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
    body = c.get(f"/api/v1/analyses/{job_id}/map?slope_limit_deg=20").json()
    assert body["statistics"]["slope_limit_deg"] == 20 and body["statistics"]["cells_total"] == 64
    assert c.get(f"/api/v1/analyses/{job_id}/map?slope_limit_deg=0").status_code == 422
