"""CRISM MTRDR spectral-summary-parameter cubes (``..._SU...J_MTR3``), read band by band.

Format, verified from the real header and label of observation FRT000047A3 (kept in
``tests/fixtures/crism``) and the PDS dataset ``MRO-M-CRISM-5-RDR-MPTARGETED-V1.0``:

* One ENVI file: ``bands`` summary parameters (60), 32-bit float, little endian, band-sequential,
  no header offset; the data ignore value is 65535.0 (``data ignore value`` in the ENVI header).
* Because each band is stored contiguously, one band (or a block of its rows) is one HTTP range
  request. The PDS Geosciences Node server answers ``Accept-Ranges: bytes``.
* Equirectangular map projection on a sphere (radius 3394839.813316312 m for the observation read),
  standard parallel 15 N, central meridian 0, east-positive longitude, planetocentric latitude,
  18 m pixels. ``map info`` gives the easting/northing of the upper-left corner of pixel (1, 1).

``x = R cos(lat1) (lon - lon0)`` and ``y = R lat`` are the projection equations of this file
(Equidistant Cylindrical). The PDS3 label gives bounds that look like pixel centres, while the ENVI
``map info`` gives the upper-left corner of the first pixel; they differ by half a pixel (9 m) and this
reader uses the ENVI map info. Nothing here interprets the parameters scientifically.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np

from app.analyzer.discovery.mars_geometry import wrap_longitude_deg
from app.schemas import BoundingBox, LonLat

RangeFetcher = Callable[[int, int], bytes]


class CrismError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SummaryCubeLayout:
    samples: int
    lines: int
    band_names: tuple[str, ...]
    ignore_value: float
    radius_m: float
    standard_parallel_deg: float
    central_meridian_deg: float
    x0_m: float                 # easting of the upper-left corner of the first pixel
    y0_m: float                 # northing of the upper-left corner of the first pixel
    pixel_m: float

    @property
    def band_bytes(self) -> int:
        return self.samples * self.lines * 4

    def band_index(self, name: str) -> int:
        try:
            return self.band_names.index(name)
        except ValueError as exc:
            raise CrismError("unknown_band", f"{name!r} is not a band of this product") from exc

    # -- georeferencing ---------------------------------------------------------------------------
    def lonlat_to_rowcol(self, p: LonLat) -> tuple[float, float]:
        """Fractional (row, col) of a position; row/col 0.0 is the upper-left corner of pixel (0, 0)."""
        lon = wrap_longitude_deg(p.longitude_deg_east - self.central_meridian_deg)
        x = self.radius_m * math.cos(math.radians(self.standard_parallel_deg)) * math.radians(lon)
        y = self.radius_m * math.radians(p.latitude_deg)
        return (self.y0_m - y) / self.pixel_m, (x - self.x0_m) / self.pixel_m

    def rowcol_to_lonlat(self, row: float, col: float) -> LonLat:
        x = self.x0_m + col * self.pixel_m
        y = self.y0_m - row * self.pixel_m
        lon = self.central_meridian_deg + math.degrees(x / (self.radius_m * math.cos(math.radians(self.standard_parallel_deg))))
        return LonLat(latitude_deg=math.degrees(y / self.radius_m), longitude_deg_east=wrap_longitude_deg(lon))

    def footprint(self) -> BoundingBox:
        nw, se = self.rowcol_to_lonlat(0, 0), self.rowcol_to_lonlat(self.lines, self.samples)
        return BoundingBox(west_deg_east=nw.longitude_deg_east, south_deg=se.latitude_deg,
                           east_deg_east=se.longitude_deg_east, north_deg=nw.latitude_deg)


def parse_layout(envi_header: str) -> SummaryCubeLayout:
    """Parse the ENVI header of a summary-parameter cube, refusing anything this reader does not handle."""
    h = envi_header.replace("\r", "")

    def num(key: str) -> float:
        m = re.search(rf"^{key}\s*=\s*([-+0-9.eE]+)", h, re.MULTILINE)
        if not m:
            raise CrismError("bad_header", f"ENVI header has no '{key}'")
        return float(m.group(1))

    if int(num("data type")) != 4 or int(num("byte order")) != 0 or int(num("header offset")) != 0:
        raise CrismError("unsupported_format", "expected 32-bit little-endian float data with no header offset")
    if not re.search(r"^interleave\s*=\s*bsq", h, re.MULTILINE | re.IGNORECASE):
        raise CrismError("unsupported_format", "expected band-sequential (bsq) storage")
    names = re.search(r"band names\s*=\s*\{([^}]*)\}", h, re.DOTALL)
    info = re.search(r"map info\s*=\s*\{([^}]*)\}", h)
    proj = re.search(r"coordinate system string\s*=\s*\{(.*)\}", h)
    if not (names and info and proj):
        raise CrismError("bad_header", "ENVI header lacks band names, map info or a coordinate system string")
    bands = tuple(n.strip() for n in names.group(1).replace("\n", " ").split(",") if n.strip())
    if len(bands) != int(num("bands")):
        raise CrismError("bad_header", "band name count does not match the band count")
    fields = [f.strip() for f in info.group(1).split(",")]
    if fields[0] != "MRO Mars Equirectangular [IAU 2000] [15.00N; 0.00E]" or int(float(fields[1])) != 1 or int(float(fields[2])) != 1:
        raise CrismError("unsupported_format", "unexpected map info (expected an equirectangular grid referenced at pixel 1,1)")
    px, py = float(fields[5]), float(fields[6])
    if abs(px - py) > 1e-9:
        raise CrismError("unsupported_format", "non-square pixels are not supported")
    radius = re.search(r'SPHEROID\["[^"]*",([0-9.]+),0', proj.group(1))
    parallel = re.search(r'Standard_Parallel_1",([-0-9.]+)', proj.group(1))
    meridian = re.search(r'Central_Meridian",([-0-9.]+)', proj.group(1))
    if not (radius and parallel and meridian) or "Equidistant_Cylindrical" not in proj.group(1):
        raise CrismError("unsupported_format", "expected an Equidistant_Cylindrical projection on a sphere")
    return SummaryCubeLayout(
        samples=int(num("samples")), lines=int(num("lines")), band_names=bands, ignore_value=num("data ignore value"),
        radius_m=float(radius.group(1)), standard_parallel_deg=float(parallel.group(1)), central_meridian_deg=float(meridian.group(1)),
        x0_m=float(fields[3]), y0_m=float(fields[4]), pixel_m=px,
    )


@dataclass(frozen=True)
class BandWindow:
    values: np.ndarray        # float32 (rows, cols); NaN where the file's ignore value is stored
    row0: int
    col0: int
    bytes_fetched: int


def pixel_window(layout: SummaryCubeLayout, bounds: BoundingBox) -> tuple[int, int, int, int] | None:
    """(row0, row1, col0, col1) of the pixels intersecting ``bounds``, or None when they do not intersect."""
    corners = [layout.lonlat_to_rowcol(LonLat(latitude_deg=lat, longitude_deg_east=lon))
               for lat in (bounds.south_deg, bounds.north_deg) for lon in (bounds.west_deg_east, bounds.east_deg_east)]
    rows, cols = [c[0] for c in corners], [c[1] for c in corners]
    row0, row1 = max(0, math.floor(min(rows))), min(layout.lines, math.ceil(max(rows)))
    col0, col1 = max(0, math.floor(min(cols))), min(layout.samples, math.ceil(max(cols)))
    return (row0, row1, col0, col1) if row1 > row0 and col1 > col0 else None


def read_band_window(layout: SummaryCubeLayout, band: str, window: tuple[int, int, int, int], fetch: RangeFetcher,
                     max_bytes: int = 32 * 1024 * 1024) -> BandWindow:
    """One range request for the window's rows of one band (full-width rows, columns cropped locally)."""
    row0, row1, col0, col1 = window
    need = (row1 - row0) * layout.samples * 4
    if need > max_bytes:
        raise CrismError("byte_limit", f"window needs {need} bytes, above the {max_bytes} byte limit")
    start = layout.band_index(band) * layout.band_bytes + row0 * layout.samples * 4
    data = fetch(start, start + need - 1)
    if len(data) != need:
        raise CrismError("short_read", f"expected {need} bytes, received {len(data)}")
    arr = np.frombuffer(data, dtype="<f4").reshape(row1 - row0, layout.samples)[:, col0:col1].astype(np.float32)
    arr[arr == np.float32(layout.ignore_value)] = np.nan
    arr[~np.isfinite(arr)] = np.nan
    return BandWindow(values=arr, row0=row0, col0=col0, bytes_fetched=len(data))
