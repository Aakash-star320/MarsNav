from pathlib import Path

import numpy as np
import pytest

from app.connectors.pds.crism_mtrdr import CrismError, parse_layout, pixel_window, read_band_window
from app.schemas import BoundingBox, LonLat

FIX = Path(__file__).parents[2] / "fixtures" / "crism"
HDR = (FIX / "frt000047a3_07_su166j_mtr3.hdr").read_text(encoding="utf-8")
LAYOUT = parse_layout(HDR)


def test_parses_the_real_header() -> None:
    assert (LAYOUT.samples, LAYOUT.lines) == (847, 808)
    assert len(LAYOUT.band_names) == 60 and LAYOUT.band_names[25] == "BD1900_2" and LAYOUT.band_names[39] == "D2300"
    assert LAYOUT.ignore_value == pytest.approx(65535.0)
    assert LAYOUT.pixel_m == 18.0 and LAYOUT.standard_parallel_deg == 15.0 and LAYOUT.central_meridian_deg == 0.0
    assert LAYOUT.radius_m == pytest.approx(3394839.813316312)
    assert LAYOUT.band_bytes == 847 * 808 * 4 and 60 * LAYOUT.band_bytes == 164250240    # file size reported by the server


def test_footprint_matches_the_pds_label() -> None:
    # Values from the PDS3 label's IMAGE_MAP_PROJECTION of the same product.
    fp = LAYOUT.footprint()
    assert fp.west_deg_east == pytest.approx(77.375951, abs=2e-4) and fp.east_deg_east == pytest.approx(77.642025, abs=2e-4)
    assert fp.south_deg == pytest.approx(18.442814, abs=2e-4) and fp.north_deg == pytest.approx(18.687974, abs=2e-4)


def test_row_col_round_trip() -> None:
    p = LAYOUT.rowcol_to_lonlat(400.5, 300.25)
    row, col = LAYOUT.lonlat_to_rowcol(p)
    assert (row, col) == (pytest.approx(400.5, abs=1e-6), pytest.approx(300.25, abs=1e-6))
    # The label's bounds refer to pixel centres and the ENVI map info to the upper-left corner, so they differ by
    # half a pixel (9 m). The reader uses the ENVI map info.
    assert LAYOUT.lonlat_to_rowcol(LonLat(latitude_deg=18.687974, longitude_deg_east=77.375951))[0] == pytest.approx(0.5, abs=0.05)


def test_window_selection_and_non_overlap() -> None:
    inside = BoundingBox(west_deg_east=77.45, south_deg=18.5, east_deg_east=77.5, north_deg=18.55)
    r0, r1, c0, c1 = pixel_window(LAYOUT, inside)
    assert 0 <= r0 < r1 <= 808 and 0 <= c0 < c1 <= 847
    assert pixel_window(LAYOUT, BoundingBox(west_deg_east=10, south_deg=0, east_deg_east=11, north_deg=1)) is None


def make_cube(fn):
    """Synthetic cube with the real layout: value = fn(band, row, col), plus ignore values."""
    b, r, c = np.indices((len(LAYOUT.band_names), LAYOUT.lines, LAYOUT.samples), dtype=np.float32)
    return fn(b, r, c).astype("<f4").tobytes()


def test_reads_exactly_one_band_with_one_range_request() -> None:
    cube = make_cube(lambda b, r, c: np.where((r == 100) & (c == 200), 65535.0, b * 1000 + r + c / 1000))
    calls = []

    def fetch(a, z):
        calls.append((a, z))
        return cube[a:z + 1]
    w = read_band_window(LAYOUT, "BD1900_2", (98, 103, 198, 203), fetch)
    assert len(calls) == 1 and w.bytes_fetched == 5 * 847 * 4
    assert w.values.shape == (5, 5) and w.row0 == 98 and w.col0 == 198
    assert w.values[0, 0] == pytest.approx(25 * 1000 + 98 + 198 / 1000, rel=1e-6)    # band 25 = BD1900_2
    assert np.isnan(w.values[2, 2]) and np.isfinite(w.values).sum() == 24          # ignore value becomes NaN


def test_guards() -> None:
    with pytest.raises(CrismError) as e:
        read_band_window(LAYOUT, "NOT_A_BAND", (0, 1, 0, 1), lambda a, b: b"")
    assert e.value.code == "unknown_band"
    with pytest.raises(CrismError) as e:
        read_band_window(LAYOUT, "D2300", (0, 808, 0, 847), lambda a, b: b"", max_bytes=1000)
    assert e.value.code == "byte_limit"
    with pytest.raises(CrismError) as e:
        read_band_window(LAYOUT, "D2300", (0, 2, 0, 5), lambda a, b: b"short")
    assert e.value.code == "short_read"


def test_refuses_formats_it_does_not_handle() -> None:
    with pytest.raises(CrismError) as e:
        parse_layout(HDR.replace("data type = 4", "data type = 2"))
    assert e.value.code == "unsupported_format"
    with pytest.raises(CrismError):
        parse_layout(HDR.replace("interleave = bsq", "interleave = bil"))
    with pytest.raises(CrismError):
        parse_layout(HDR.replace("bands   = 60", "bands   = 59"))
