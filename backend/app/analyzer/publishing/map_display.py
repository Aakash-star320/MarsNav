"""Turn a verified terrain bundle into map-ready display layers and a DEM.

Images are plate-carree rasters in the canonical angular display projection; the terrain grid is
already regular in longitude/latitude, so no resampling is needed. Invalid cells are fully
transparent (never coloured as zero). Large grids are decimated by an integer stride for display
only, and the package says so. Numerical analysis keeps using the full-resolution bundle.

Conventions required by the map module (see ``docs/mars-map/INTEGRATION.md``):
* DEM samples are point-registered at cell centres, and ``dem.bounds`` is the extent of the sample
  points. Every layer's ``bounds`` equals ``dem.bounds`` (the 3D view rejects overlays otherwise), so
  images are draped over the sample extent; this shifts edges by half a source cell.
"""
from __future__ import annotations

import math
import struct
import zlib
from typing import Callable

import numpy as np

from app.analyzer.preprocessing.terrain_bundle import SPHERE_RADIUS_M, TerrainManifest
from app.schemas import BoundingBox, CoverageStatus, ProcessedLayer, ScienceTarget
from app.schemas.map_display import DemPayload, DemProjection, MapLayerEntry, MapPackage

from .statistics import compute_statistics

DEFAULT_MAX_DIM = 257
SOURCE_LABEL = "USGS MOLA 463 m global DEM (interpolated product)"
# (array name, layer kind, colours low->high, fixed range or None for data range, units, title)
LAYER_SPECS = [
    ("elevation_m", "elevation", ["#305096", "#ed9b37"], None, "m", "Elevation"),
    ("slope_deg", "slope", ["#46b9a0", "#fa3c28"], (0.0, 35.0), "deg", "Slope"),
    ("roughness_m", "roughness", ["#5f50a0", "#cd78d7"], None, "m", "Roughness (3x3 elevation std)"),
]


def _hex(c: str) -> np.ndarray:
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)


def png_bytes(rgba: np.ndarray) -> bytes:
    """Minimal PNG encoder (8-bit RGBA, no interlace) using only the standard library."""
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise ValueError("expected an (h, w, 4) uint8 array")
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def colorize(values: np.ndarray, valid: np.ndarray, lo: float, hi: float, colors: list[str]) -> np.ndarray:
    ok = valid & np.isfinite(values)
    t = np.clip((np.where(ok, values, lo) - lo) / (hi - lo if hi > lo else 1.0), 0.0, 1.0)[..., None]
    rgb = _hex(colors[0]) * (1 - t) + _hex(colors[1]) * t
    out = np.zeros(values.shape + (4,), dtype=np.uint8)
    out[..., :3] = np.rint(rgb).astype(np.uint8)
    out[..., 3] = np.where(ok, 255, 0)
    return out


def _stride(shape: tuple[int, int], max_dim: int) -> int:
    return max(1, math.ceil(max(shape) / max_dim))


def display_arrays(arrays: dict[str, np.ndarray], max_dim: int = DEFAULT_MAX_DIM) -> tuple[dict[str, np.ndarray], int]:
    """Decimate by an integer stride, keeping a first-and-last-sample-aligned uniform grid."""
    rows, cols = arrays["valid"].shape
    k = _stride((rows, cols), max_dim)
    nr, nc = (rows - 1) // k + 1, (cols - 1) // k + 1
    return {name: a[::k, ::k][:nr, :nc] for name, a in arrays.items()}, k


def _dem_geometry(manifest: TerrainManifest, shape: tuple[int, int], k: int) -> tuple[list[float], DemProjection, BoundingBox]:
    g = manifest.grid
    b = manifest.bounds
    lat0, lon0 = (b.north_deg + b.south_deg) / 2, (b.east_deg_east + b.west_deg_east) / 2
    dx, dy = g.pixel_size_x_m * k, g.pixel_size_y_m * k
    x0, y0 = g.origin_x_m + g.pixel_size_x_m / 2, g.origin_y_m - g.pixel_size_y_m / 2      # first cell centre
    rows, cols = shape
    cos0 = math.cos(math.radians(lat0))
    west = lon0 + math.degrees(x0 / (SPHERE_RADIUS_M * cos0))
    east = lon0 + math.degrees((x0 + (cols - 1) * dx) / (SPHERE_RADIUS_M * cos0))
    north = lat0 + math.degrees(y0 / SPHERE_RADIUS_M)
    south = lat0 + math.degrees((y0 - (rows - 1) * dy) / SPHERE_RADIUS_M)
    return ([x0, dx, 0.0, y0, 0.0, -dy],
            DemProjection(radius_m=SPHERE_RADIUS_M, latitude_origin_deg=lat0, longitude_origin_deg_east=lon0),
            BoundingBox(west_deg_east=west, south_deg=south, east_deg_east=east, north_deg=north))


def _range(a: np.ndarray, valid: np.ndarray, fixed: tuple[float, float] | None) -> tuple[float, float]:
    if fixed:
        return fixed
    v = a[valid & np.isfinite(a)]
    if v.size == 0:
        return 0.0, 1.0
    lo, hi = float(np.percentile(v, 2)), float(np.percentile(v, 98))
    return (lo, hi) if hi > lo else (float(v.min()), float(v.min()) + 1.0)


def render_layer_png(arrays: dict[str, np.ndarray], array_name: str, max_dim: int = DEFAULT_MAX_DIM) -> bytes:
    disp, _ = display_arrays(arrays, max_dim)
    spec = next(s for s in LAYER_SPECS if s[0] == array_name)
    lo, hi = _range(disp[array_name], disp["valid"], spec[3])
    return png_bytes(colorize(disp[array_name], disp["valid"], lo, hi, spec[2]))


def build_map_package(
    manifest: TerrainManifest, arrays: dict[str, np.ndarray], layer_url: Callable[[str], str], max_dim: int = DEFAULT_MAX_DIM,
    slope_limit_deg: float = 12.0, science_targets: list[ScienceTarget] | None = None,
) -> MapPackage:
    disp, k = display_arrays(arrays, max_dim)
    shape = disp["valid"].shape
    affine, projection, bounds = _dem_geometry(manifest, shape, k)
    notes = [
        "Layers and DEM are display-resolution copies of the analysis terrain; the full-resolution bundle is used for analysis.",
        "Images are draped over the DEM sample extent (half a source cell smaller than the cell edges).",
    ]
    if k > 1:
        notes.append(f"Decimated by a stride of {k} for display ({arrays['valid'].shape} -> {shape}).")
    native = manifest.sources[0].get("native_resolution_m")
    resolution = float(native) if isinstance(native, (int, float)) else manifest.grid.pixel_size_y_m
    dataset_ids = [manifest.sources[0]["dataset_id"]] if manifest.sources else []
    entries: list[MapLayerEntry] = []
    for array_name, kind, colors, fixed, units, title in LAYER_SPECS:
        a, valid = disp[array_name], disp["valid"]
        finite = np.isfinite(a)
        pct = 100.0 * float(finite.mean())
        if pct <= 0:
            continue
        lo, hi = _range(a, valid, fixed)
        cov = CoverageStatus.available if pct >= 99.99 else CoverageStatus.partial
        entries.append(MapLayerEntry(
            layer=ProcessedLayer(
                id=_layer_id(manifest, kind), kind=kind, uri=layer_url(kind), bounds=bounds, resolution_m_per_px=resolution,
                valid_percent=pct, units=units, dataset_ids=dataset_ids, grid=manifest.grid, availability=cov,
                limitations=list(manifest.limitations), style_hint={"range": [lo, hi], "stride": k},
            ),
            source=SOURCE_LABEL, synthetic=False, coverage=cov.value, colors=colors,
            legend=f"{title}: {lo:.0f} to {hi:.0f} {units} (colour scale; {SOURCE_LABEL}; missing data is transparent)"
            if not fixed else f"{title}: {lo:.0f} to {hi:.0f} {units} (fixed colour scale; {SOURCE_LABEL})",
        ))
    z = disp["elevation_m"]
    dem = DemPayload(
        synthetic=False, width=shape[1], height=shape[0], bounds=bounds, projection=projection, affine=affine,
        vertical_datum="not stated in the source file header",
        values=[None if not np.isfinite(v) else round(float(v), 3) for v in z.ravel()],
    )
    return MapPackage(
        analysis_id=str(manifest.analysis_id), layers=entries, dem=dem, notes=notes,
        statistics=compute_statistics(manifest, arrays, slope_limit_deg, len(science_targets or [])),
        science_targets=list(science_targets or []),
    )


def _layer_id(manifest: TerrainManifest, kind: str):
    from uuid import uuid5
    return uuid5(manifest.analysis_id, f"map-{kind}")
