import os

import httpx
import numpy as np
import pytest

from app.analyzer.preprocessing.terrain import slope_deg
from app.connectors.usgs import mola
from app.connectors.usgs.mola import LAYOUT, MolaError, MolaLayout, dataset_record, http_range_fetcher, pixel_window, read_window
from app.schemas import BoundingBox

# Small synthetic raster with the same structure as the real file (rows contiguous, int16, nodata).
SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, nodata=-32768,
                   deg_per_px=0.5, pixel_size_m=1000.0, file_size=0, etag="test")


def make_blob(fn, layout=SMALL):
    rows, cols = np.indices((layout.height, layout.width))
    arr = fn(rows, cols).astype("<i2")
    return b"\0" * layout.data_offset + arr.tobytes()


def fetcher(blob):
    return lambda a, b: blob[a:b + 1]


def box(w, s, e, n):
    return BoundingBox(west_deg_east=w, south_deg=s, east_deg_east=e, north_deg=n)


def test_real_layout_constants_are_consistent() -> None:
    assert LAYOUT.width * LAYOUT.deg_per_px == 360 and LAYOUT.height * LAYOUT.deg_per_px == 180
    assert LAYOUT.row_bytes == 92160
    assert LAYOUT.data_offset + LAYOUT.height * LAYOUT.row_bytes == 2123551373   # last strip end read from the header


def test_window_maps_rows_and_columns() -> None:
    # Jezero area: row 0 is +90 latitude, column 0 is -180 longitude.
    r0, r1, c0, c1 = pixel_window(box(77.3, 18.3, 77.5, 18.5), LAYOUT, halo_px=0)
    assert r0 == int((90 - 18.5) / 0.0078125) and c0 == int((77.3 + 180) / 0.0078125)
    assert 0 < r1 - r0 < 40 and 0 < c1 - c0 < 40


def test_read_window_returns_exact_pixels_and_bounds() -> None:
    blob = make_blob(lambda r, c: r * 10 + c % 7)
    w = read_window(box(10.0, 20.0, 12.0, 22.0), fetcher(blob), SMALL, halo_px=0)
    assert w.bounds.west_deg_east == 10.0 and w.bounds.east_deg_east == 12.0
    assert w.bounds.north_deg == 22.0 and w.bounds.south_deg == 20.0
    row, col = 136, 380                  # (90-22)/0.5 and (10+180)/0.5
    assert w.row0 == row and w.col0 == col
    assert w.elevation_m[0, 0] == row * 10 + col % 7
    assert w.elevation_m.shape == (4, 4)
    assert w.bytes_fetched == 4 * 4 * 2               # only the window's columns of each row are requested (int16)


def test_nodata_becomes_nan_and_invalid() -> None:
    blob = make_blob(lambda r, c: np.where(c == 382, -32768, 100))
    w = read_window(box(10.0, 20.0, 12.0, 22.0), fetcher(blob), SMALL, halo_px=0)
    assert not w.valid[:, 382 - w.col0].any() and np.isnan(w.elevation_m[:, 382 - w.col0]).all()
    assert w.valid[:, 0].all()


def test_byte_limit_is_enforced_before_fetching() -> None:
    def boom(a, b):
        raise AssertionError("must not fetch")
    with pytest.raises(MolaError) as exc:
        read_window(box(0.0, -60.0, 10.0, 60.0), boom, SMALL, max_bytes=1000)
    assert exc.value.code == "byte_limit"


def test_antimeridian_is_rejected() -> None:
    edge = BoundingBox.model_construct(west_deg_east=170.0, south_deg=0.0, east_deg_east=180.0, north_deg=10.0)
    with pytest.raises(MolaError) as exc:
        pixel_window(edge, SMALL)
    assert exc.value.code == "antimeridian"


def test_short_read_is_reported() -> None:
    blob = make_blob(lambda r, c: r)
    with pytest.raises(MolaError) as exc:
        read_window(box(10.0, 20.0, 12.0, 22.0), lambda a, b: blob[a:b], SMALL)
    assert exc.value.code == "short_read"


def test_window_feeds_terrain_slope_with_real_spacing() -> None:
    # East-rising ramp: 100 m per pixel over a 1000 m pixel => atan(0.1) at the equator.
    blob = make_blob(lambda r, c: c * 100)
    w = read_window(box(10.0, -2.0, 12.0, 2.0), fetcher(blob), SMALL, halo_px=1)
    s, ok = slope_deg(w.elevation_m, w.valid, w.pixel_size_x_m, w.pixel_size_y_m)
    assert np.nanmean(s[ok]) == pytest.approx(np.degrees(np.arctan(100 / w.pixel_size_x_m)), rel=1e-6)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_fetcher_accepts_206_with_exact_length() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Range"] == "bytes=10-19"
        return httpx.Response(206, content=b"x" * 10, headers={"content-type": "image/tiff"})
    assert http_range_fetcher("https://example.test/a.tif", client=_client(handler))(10, 19) == b"x" * 10


@pytest.mark.parametrize("response, code", [
    (httpx.Response(200, content=b"x" * 10), "bad_status"),                      # server ignored the Range header
    (httpx.Response(206, content=b"<html>", headers={"content-type": "text/html"}), "bad_content"),
])
def test_http_fetcher_rejects_bad_replies(response, code) -> None:
    with pytest.raises(MolaError) as exc:
        http_range_fetcher("https://example.test/a.tif", client=_client(lambda r: response))(0, 9)
    assert exc.value.code == code


def test_http_fetcher_retries_short_reads_then_gives_up(monkeypatch) -> None:
    monkeypatch.setattr(mola.time, "sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(206, content=b"xx", headers={"content-type": "image/tiff"})
    with pytest.raises(MolaError) as exc:
        http_range_fetcher("https://example.test/a.tif", retries=2, client=_client(handler))(0, 9)
    assert exc.value.code == "fetch_failed" and len(calls) == 3


def test_http_fetcher_retries_transport_errors(monkeypatch) -> None:
    monkeypatch.setattr(mola.time, "sleep", lambda s: None)
    state = {"n": 0}

    def handler(req):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(206, content=b"y" * 4, headers={"content-type": "image/tiff"})
    assert http_range_fetcher("https://example.test/a.tif", client=_client(handler))(0, 3) == b"yyyy"


def test_dataset_record_is_honest_about_limits() -> None:
    r = dataset_record()
    assert r.source == "usgs" and r.category.value == "elevation" and r.resolution_m_per_px == pytest.approx(463.09, abs=0.01)
    assert r.coverage.status.value == "available" and r.coverage.footprint.north_deg == 90.0
    assert r.source_spatial_metadata.vertical_datum is None
    assert any("463 m" in s for s in r.limitations) and any("vertical datum" in s.lower() for s in r.limitations)


@pytest.mark.skipif(os.environ.get("RUN_REAL_DATA") != "1", reason="network test; set RUN_REAL_DATA=1")
def test_real_mola_window_over_jezero() -> None:
    """Reads 28 small row slices from the live USGS file and sanity-checks physical plausibility."""
    w = read_window(box(77.3, 18.3, 77.5, 18.5), http_range_fetcher())
    assert w.valid.all()
    assert -9000 < np.nanmin(w.elevation_m) and np.nanmax(w.elevation_m) < 22000     # Mars elevation extremes
    s, ok = slope_deg(w.elevation_m, w.valid, w.pixel_size_x_m, w.pixel_size_y_m)
    assert ok.any() and np.nanmax(s) < 30                                            # coarse 463 m grid is smooth
    assert w.bytes_fetched == 28 * (w.elevation_m.shape[1] * 2)
