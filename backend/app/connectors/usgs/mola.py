"""Mars MGS MOLA global DEM (463 m) windowed reader.

Source: ``Mars_MGS_MOLA_DEM_mosaic_global_463m.tif`` published by USGS Astrogeology
(catalog: https://fdp.astrogeology.usgs.gov/fdp/mars/, "Interpolated MOLA DEM", 463 mpp / 128 ppd).

Every constant below was read from the live file's TIFF header (classic TIFF, directory stored at the
end of the file) and cross-checked on 2026-11-14:

* 46080 x 23040 pixels, 16-bit signed integer, one sample, no compression, planar config 2,
  one row per strip (92160 bytes each), strips contiguous from byte 184973 (verified for all 23040).
* ModelTiepoint x = -pi*R, y = pi/2*R and pixel scale 463.0935 m => exactly 0.0078125 deg/pixel,
  row 0 at +90 deg latitude, column 0 at -180 deg longitude (east positive).
* GDAL_NODATA = -32768. CRS text: "Equirectangular Mars", GCS_Mars sphere, radius 3396190 m.
* The server answers HTTP range requests (``Accept-Ranges: bytes``).

NOT stated in the header and therefore not claimed as verified: the vertical unit (the USGS catalog
lists the product as Elevation; metres are assumed) and the vertical datum.

Because rows are contiguous and uncompressed, a region is read with one byte-range request for whole
rows, then cropped to its columns locally. The global raster is never downloaded.
"""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable
from uuid import NAMESPACE_URL, uuid5

import httpx
import numpy as np

from app.schemas import (
    BoundingBox,
    CoverageStatus,
    DatasetCategory,
    DatasetCoverage,
    DatasetRecord,
    FreshnessState,
    SourceSpatialMetadata,
)

MOLA_URL = "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif"
CATALOG_URL = "https://fdp.astrogeology.usgs.gov/fdp/mars/"
PRODUCT_ID = "Mars_MGS_MOLA_DEM_mosaic_global_463m"

RangeFetcher = Callable[[int, int], bytes]   # (first_byte, last_byte_inclusive) -> bytes


class MolaError(RuntimeError):
    """Structured MOLA read failure; ``code`` separates limits, bad replies and bad requests."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


FETCH_WORKERS = 16     # concurrent row requests
TRANSIENT_STATUS = {429, 500, 502, 503, 504}   # worth retrying: the server is busy or failed for a moment


@dataclass(frozen=True)
class MolaLayout:
    url: str = MOLA_URL
    width: int = 46080
    height: int = 23040
    bytes_per_pixel: int = 2
    data_offset: int = 184973
    nodata: int = -32768
    deg_per_px: float = 0.0078125
    pixel_size_m: float = 463.0935415503709     # equatorial pixel size from the file's ModelPixelScale
    file_size: int = 2125771142
    etag: str = "cccf7001294ee9f503b13318eab83086-254"

    @property
    def row_bytes(self) -> int:
        return self.width * self.bytes_per_pixel


LAYOUT = MolaLayout()


@dataclass(frozen=True)
class MolaWindow:
    elevation_m: np.ndarray        # float32, NaN where nodata
    valid: np.ndarray              # bool
    bounds: BoundingBox            # exact pixel-edge bounds of the returned window
    row0: int
    col0: int
    pixel_size_y_m: float
    pixel_size_x_m: float          # metric east-west spacing at the window's centre latitude
    bytes_fetched: int
    provenance: dict[str, object]


def pixel_window(bounds: BoundingBox, layout: MolaLayout = LAYOUT, halo_px: int = 0) -> tuple[int, int, int, int]:
    """(row0, row1, col0, col1) half-open pixel window covering ``bounds`` plus a halo."""
    if bounds.east_deg_east >= 180.0:
        raise MolaError("antimeridian", "window reaches +180 degrees; split the region")
    row0 = math.floor((90.0 - bounds.north_deg) / layout.deg_per_px) - halo_px
    row1 = math.ceil((90.0 - bounds.south_deg) / layout.deg_per_px) + halo_px
    col0 = math.floor((bounds.west_deg_east + 180.0) / layout.deg_per_px) - halo_px
    col1 = math.ceil((bounds.east_deg_east + 180.0) / layout.deg_per_px) + halo_px
    row0, row1 = max(row0, 0), min(row1, layout.height)
    col0, col1 = max(col0, 0), min(col1, layout.width - 1)   # keep east edge below +180
    if row1 <= row0 or col1 <= col0:
        raise MolaError("empty_window", "region does not intersect the raster")
    return row0, row1, col0, col1


def read_window(
    bounds: BoundingBox, fetch: RangeFetcher, layout: MolaLayout = LAYOUT, halo_px: int = 1,
    max_bytes: int = 64 * 1024 * 1024,
) -> MolaWindow:
    row0, row1, col0, col1 = pixel_window(bounds, layout, halo_px)
    n_rows = row1 - row0
    row_len = (col1 - col0) * layout.bytes_per_pixel
    need = n_rows * row_len
    if need > max_bytes:
        raise MolaError("byte_limit", f"region needs {need} bytes of MOLA samples, above the {max_bytes} byte limit; choose a smaller region")
    # Only the window's columns of each row are requested (a few hundred bytes, not the planet-wide 92 KB row), and
    # the rows are fetched concurrently: the region costs a handful of round trips instead of one multi-MB download.
    def one_row(r: int) -> bytes:
        start = layout.data_offset + r * layout.row_bytes + col0 * layout.bytes_per_pixel
        data = fetch(start, start + row_len - 1)
        if len(data) != row_len:
            raise MolaError("short_read", f"expected {row_len} bytes for row {r}, received {len(data)}")
        return data
    with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, n_rows)) as pool:
        rows = list(pool.map(one_row, range(row0, row1)))
    data = b"".join(rows)
    raw = np.frombuffer(data, dtype="<i2").reshape(n_rows, col1 - col0)
    valid = raw != layout.nodata
    elevation = np.where(valid, raw.astype(np.float32), np.float32(np.nan))
    d = layout.deg_per_px
    win = BoundingBox(
        west_deg_east=-180.0 + col0 * d, south_deg=90.0 - row1 * d,
        east_deg_east=-180.0 + col1 * d, north_deg=90.0 - row0 * d,
    )
    centre_lat = (win.north_deg + win.south_deg) / 2
    return MolaWindow(
        elevation_m=elevation, valid=valid, bounds=win, row0=row0, col0=col0,
        pixel_size_y_m=layout.pixel_size_m,
        pixel_size_x_m=layout.pixel_size_m * math.cos(math.radians(centre_lat)),
        bytes_fetched=len(data),
        provenance={
            "product_id": PRODUCT_ID, "url": layout.url, "etag": layout.etag, "native_resolution_m": layout.pixel_size_m,
            "nodata": layout.nodata, "vertical_unit": "metres (assumed from catalog 'Elevation'; not in file header)",
            "vertical_datum": "not stated in file header",
        },
    )


def http_range_fetcher(url: str = MOLA_URL, timeout_s: float = 60.0, retries: int = 4, client: httpx.Client | None = None) -> RangeFetcher:
    """Range fetcher with status/content checks, bounded retries and exponential backoff."""
    # One pooled client for every request this fetcher makes (thread-safe), so concurrent row reads reuse
    # connections instead of paying a new TLS handshake each.
    c = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(timeout_s, connect=15.0),
                               limits=httpx.Limits(max_connections=32, max_keepalive_connections=32))

    def fetch(first: int, last: int) -> bytes:
        expected = last - first + 1
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                r = c.get(url, headers={"Range": f"bytes={first}-{last}"})
            except httpx.TransportError as exc:          # network trouble: retry with backoff
                last_error = exc
            else:
                ctype = r.headers.get("content-type", "")
                if r.status_code in TRANSIENT_STATUS:          # a busy or briefly failing server: retry with backoff
                    last_error = MolaError("bad_status", f"server answered {r.status_code}")
                elif r.status_code != 206:
                    raise MolaError("bad_status", f"expected 206 Partial Content, got {r.status_code}")
                elif "text/html" in ctype:
                    raise MolaError("bad_content", "server returned an HTML page instead of raster bytes")
                elif len(r.content) == expected:
                    return r.content
                else:
                    last_error = MolaError("short_read", f"expected {expected} bytes, received {len(r.content)}")
            if attempt < retries:
                time.sleep(0.5 * 2 ** attempt)
        raise MolaError("fetch_failed", f"gave up after {retries + 1} attempts: {last_error}")
    return fetch


def dataset_record(layout: MolaLayout = LAYOUT) -> DatasetRecord:
    """Catalog entry for the global MOLA DEM (always global coverage; coarse by nature)."""
    return DatasetRecord(
        id=uuid5(NAMESPACE_URL, f"usgs:{PRODUCT_ID}:{layout.etag}"),
        source="usgs", product_id=PRODUCT_ID, version=layout.etag, instrument="MOLA",
        category=DatasetCategory.elevation, processing_level="interpolated global DEM mosaic",
        resolution_m_per_px=layout.pixel_size_m,
        coverage=DatasetCoverage(
            status=CoverageStatus.available, percent_of_aoi=100.0, valid_percent=None,
            footprint=BoundingBox(west_deg_east=-180.0, south_deg=-90.0, east_deg_east=179.9921875, north_deg=90.0),
        ),
        freshness=FreshnessState.unable_to_verify, download_url=layout.url, provenance_url=CATALOG_URL,
        source_spatial_metadata=SourceSpatialMetadata(
            latitude_type="spherical GCS_Mars (no planetocentric/planetographic distinction on a sphere)",
            longitude_direction="east (GeoTIFF projected-X convention; not separately labelled)",
            longitude_domain="-180-180", horizontal_datum="D_Mars (sphere)", vertical_datum=None,
            body_name="Mars", radii_m=[3396190.0, 3396190.0],
        ),
        limitations=[
            "Coarse 463 m grid: supports broad planning only, not astronaut-scale hazard or obstacle detection.",
            "Vertical unit assumed metres from the catalog 'Elevation' label; the file header has no unit tag.",
            "Vertical datum is not stated in the file header.",
            "Interpolated product: pixel size is not independent measurement spacing.",
            "ETag is the S3 multipart entity tag, used as a version token, not a content checksum.",
        ],
    )
