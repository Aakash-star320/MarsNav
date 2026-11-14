import os
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
import pytest

from app.analyzer.preprocessing.terrain_bundle import TerrainBundleError, build_terrain_bundle, load_terrain_bundle
from app.connectors.usgs.mola import LAYOUT, MolaLayout, dataset_record, http_range_fetcher, read_window
from app.schemas import BoundingBox

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
AID = UUID("00000000-0000-0000-0000-0000000000aa")
WHEN = datetime(2026, 11, 14, tzinfo=timezone.utc)
AOI = BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=14.0, north_deg=24.0)


def window(fn=lambda r, c: 100 * c):
    rows, cols = np.indices((SMALL.height, SMALL.width))
    blob = b"\0" * SMALL.data_offset + fn(rows, cols).astype("<i2").tobytes()
    return read_window(AOI, lambda a, b: blob[a:b + 1], SMALL, halo_px=1)


def build(tmp_path, **kw):
    return build_terrain_bundle(window(**kw), dataset_record(), AID, tmp_path, generated_at=WHEN)


def test_bundle_round_trips_and_is_aligned(tmp_path) -> None:
    b = build(tmp_path)
    manifest, arrays = load_terrain_bundle(tmp_path / str(AID) / "terrain.manifest.json")
    assert manifest == b.manifest and manifest.shape == (8, 8)          # 4 deg / 0.5 deg = 8 cells, halo trimmed
    assert {a.shape for a in arrays.values()} == {(8, 8)}
    assert arrays["valid"].all() and np.isfinite(arrays["elevation_m"]).all()


def test_halo_is_trimmed_and_bounds_match_the_request(tmp_path) -> None:
    b = build(tmp_path)
    bb = b.manifest.bounds
    assert (bb.west_deg_east, bb.south_deg, bb.east_deg_east, bb.north_deg) == (10.0, 20.0, 14.0, 24.0)


def test_grid_metadata_is_consistent(tmp_path) -> None:
    g = build(tmp_path).manifest.grid
    a = g.affine_transform
    assert (a[0], a[4]) == (g.pixel_size_x_m, -g.pixel_size_y_m) and (a[2], a[5]) == (g.origin_x_m, g.origin_y_m)
    assert g.north_up and g.raster_rows_increase_south
    assert g.pixel_size_x_m < g.pixel_size_y_m                        # east-west cells shrink away from the equator
    assert "Mars sphere" in g.crs_wkt and "Earth" not in g.crs_wkt


def test_layers_are_valid_contract_objects(tmp_path) -> None:
    layers = build(tmp_path).layers
    assert [l.kind for l in layers] == ["elevation", "slope", "roughness", "validity", "source"]
    assert all(l.uri.startswith(f"{AID}/terrain.npz#") for l in layers)
    assert all(l.resolution_m_per_px == pytest.approx(463.09, abs=0.01) for l in layers)
    assert all(l.provenance.output_checksum_sha256 == build(tmp_path).manifest.sha256 for l in layers)
    assert layers[0].limitations


def test_slope_of_a_known_ramp_and_flags(tmp_path) -> None:
    build(tmp_path)
    _, arrays = load_terrain_bundle(tmp_path / str(AID) / "terrain.manifest.json")
    # 100 m rise per source column; the synthetic source has 1000 m pixels, so east-west spacing
    # at the window's centre latitude (22 deg) is 1000 * cos(22 deg).
    expected_deg = np.degrees(np.arctan(100 / (1000.0 * np.cos(np.radians(22.0)))))
    assert np.allclose(arrays["slope_deg"], expected_deg, rtol=1e-3)
    assert (arrays["quality_flags"] & 1).all() and (arrays["quality_flags"] & 2).all()   # coarse + interpolated


def test_nodata_is_preserved_not_filled(tmp_path) -> None:
    b = build(tmp_path, fn=lambda r, c: np.where((r == 135) & (c == 382), -32768, 50))
    _, arrays = load_terrain_bundle(tmp_path / str(AID) / "terrain.manifest.json")
    assert not arrays["valid"].all() and np.isnan(arrays["elevation_m"][~arrays["valid"]]).all()
    assert (arrays["source_id"][~arrays["valid"]] == 255).all()
    assert b.layers[3].valid_percent < 100
    assert b.layers[1].valid_percent < b.layers[0].valid_percent + 1e-9 or b.layers[1].valid_percent < 100   # slope loses cells next to missing data


def test_tampered_array_file_is_rejected(tmp_path) -> None:
    build(tmp_path)
    npz = tmp_path / str(AID) / "terrain.npz"
    npz.write_bytes(npz.read_bytes() + b"x")
    with pytest.raises(TerrainBundleError, match="checksum"):
        load_terrain_bundle(tmp_path / str(AID) / "terrain.manifest.json")


def test_no_partial_files_are_left_behind(tmp_path) -> None:
    build(tmp_path)
    assert sorted(p.name for p in (tmp_path / str(AID)).iterdir()) == ["terrain.manifest.json", "terrain.npz"]


def test_output_is_deterministic(tmp_path) -> None:
    a = build(tmp_path / "a").manifest
    b = build(tmp_path / "b").manifest
    assert a.sha256 == b.sha256


def test_too_small_window_is_rejected(tmp_path) -> None:
    tiny = read_window(BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=10.5, north_deg=20.5),
                       lambda a, b: bytes(b - a + 1), SMALL, halo_px=1)
    with pytest.raises(TerrainBundleError):
        build_terrain_bundle(tiny, dataset_record(), AID, tmp_path, halo_px=2)


@pytest.mark.skipif(os.environ.get("RUN_REAL_DATA") != "1", reason="network test; set RUN_REAL_DATA=1")
def test_real_mola_bundle_over_jezero(tmp_path) -> None:
    win = read_window(BoundingBox(west_deg_east=77.3, south_deg=18.3, east_deg_east=77.5, north_deg=18.5), http_range_fetcher())
    b = build_terrain_bundle(win, dataset_record(), AID, tmp_path)
    manifest, arrays = load_terrain_bundle(tmp_path / str(AID) / "terrain.manifest.json")
    assert manifest.shape == arrays["elevation_m"].shape and arrays["valid"].all()
    assert b.manifest.grid.pixel_size_y_m == pytest.approx(463.08, abs=0.1)
    assert np.nanmax(arrays["slope_deg"]) < 30
