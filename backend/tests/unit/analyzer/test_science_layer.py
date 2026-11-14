import struct
import zlib
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.analyzer.publishing.science_layer import ScienceLayer, load_science_layer, render_science_png, save_science_layer
from app.api.routes import analyses
from app.connectors.usgs.mola import MolaLayout
from app.schemas import BoundingBox, CreateAnalysisRequest, RegionOfInterest

from .test_crism_science import AOI, CENTER, LAYOUT, FakeCube, cube_with_blob, science_deps

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
_r, _c = np.indices((SMALL.height, SMALL.width))
BLOB = b"\0" * SMALL.data_offset + (10 * _r + 100 * _c).astype("<i2").tobytes()
MISSION = UUID("00000000-0000-0000-0000-0000000000ff")


def decode(png: bytes) -> np.ndarray:
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(png):
        n, tag = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    return np.stack([np.frombuffer(raw[i * (w * 4 + 1) + 1:(i + 1) * (w * 4 + 1)], dtype=np.uint8).reshape(w, 4) for i in range(h)])


def layer(values):
    return ScienceLayer(values=np.asarray(values, dtype=np.float32), bounds=BoundingBox(west_deg_east=77.4, south_deg=18.5, east_deg_east=77.5, north_deg=18.6),
                        product_id="frt000047a3_07_if166j_mtr3", pixel_m=18.0)


def test_render_is_transparent_where_there_is_no_data_or_no_evidence() -> None:
    rgba = decode(render_science_png(layer([[np.nan, 0.1], [0.6, 1.0]])))
    assert rgba[0, 0, 3] == 0 and rgba[0, 1, 3] == 0                         # no data, and evidence below the fade level
    assert 0 < rgba[1, 0, 3] < rgba[1, 1, 3] == 255                          # stronger evidence is more opaque


def test_save_and_load_round_trip_and_corruption_is_treated_as_absent(tmp_path) -> None:
    save_science_layer(tmp_path, layer([[0.2, np.nan], [0.7, 0.9]]))
    back = load_science_layer(tmp_path)
    assert back.product_id.startswith("frt") and np.array_equal(back.values, layer([[0.2, np.nan], [0.7, 0.9]]).values, equal_nan=True)
    (tmp_path / "science.npz").write_bytes((tmp_path / "science.npz").read_bytes() + b"x")
    assert load_science_layer(tmp_path) is None
    assert load_science_layer(tmp_path / "missing") is None


def client_for(tmp_path, objective):
    deps = AnalyzerDeps(fetch_range=lambda a, b: BLOB[a:b + 1], out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9,
                        science=science_deps(FakeCube(cube_with_blob(CENTER))))
    svc = AnalysisService(deps, clock=lambda: datetime(2026, 11, 14, tzinfo=timezone.utc))
    app = FastAPI()
    app.include_router(analyses.router, prefix="/api/v1")
    app.dependency_overrides[analyses.get_service] = lambda: svc
    c = TestClient(app)
    req = CreateAnalysisRequest(mission_id=MISSION, objective=objective, roi=RegionOfInterest(name="t", bounds=AOI, analysis_margin_m=0))
    job_id = c.post("/api/v1/analyses", json=req.model_dump(mode="json")).json()["id"]
    svc.wait_idle()
    return c, job_id


def test_science_layer_is_published_and_served_for_a_science_objective(tmp_path) -> None:
    c, job_id = client_for(tmp_path, "find hydrated minerals")
    pkg = c.get(f"/api/v1/analyses/{job_id}/map").json()
    kinds = [entry["layer"]["kind"] for entry in pkg["layers"]]
    assert kinds == ["elevation", "slope", "roughness", "science"] and len(pkg["science_targets"]) == 1
    sci = pkg["layers"][3]
    assert sci["synthetic"] is False and "heuristic" in sci["legend"] and sci["layer"]["uri"].endswith("/layers/science.png")
    b = sci["layer"]["bounds"]
    assert b["west_deg_east"] < CENTER.longitude_deg_east < b["east_deg_east"] and b["south_deg"] < CENTER.latitude_deg < b["north_deg"]
    assert pkg["statistics"]["science_candidates"] == 1
    png = c.get(sci["layer"]["uri"].replace("http://testserver", ""))
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    rgba = decode(png.content)
    assert (rgba[..., 3] > 200).any() and (rgba[..., 3] == 0).any()           # the planted signature is strongly visible, the rest is transparent


def test_no_science_layer_for_terrain_only_objectives(tmp_path) -> None:
    c, job_id = client_for(tmp_path, "terrain overview")
    kinds = [entry["layer"]["kind"] for entry in c.get(f"/api/v1/analyses/{job_id}/map").json()["layers"]]
    assert "science" not in kinds
    assert c.get(f"/api/v1/analyses/{job_id}/layers/science.png").status_code == 404
