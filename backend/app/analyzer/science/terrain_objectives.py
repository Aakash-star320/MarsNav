"""Terrain-based science objectives: candidate sites found from the elevation, slope and roughness arrays alone.

Pure functions over the arrays of a terrain bundle (``terrain.npz``): nothing is downloaded and nothing is invented.
Every target is a patch or a cell of the analysed grid. Measured values (a cell count, a slope, an elevation) are marked
as measured; the rules that turn them into a ranking are marked as heuristic and their thresholds are the constants below.
The grid is 463 m wide, so a "site" is a patch of cells, not a surveyed landing site.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping
from uuid import UUID, uuid5

import numpy as np
from scipy import ndimage

from app.schemas import BoundingBox, LocalGridMetadata, LonLat, ScienceEvidence, ScienceTarget

from .objectives import FLAT_SITES as FLAT_SITES_ID, VANTAGE as VANTAGE_ID

RECIPE_FLAT = "flat-safe-sites/1"
RECIPE_VANTAGE = "high-vantage-points/1"

# -- flat safe sites -----------------------------------------------------------------------------------------
FLAT_SLOPE_DEG = 5.0          # a cell is gentle when its slope is below this
FLAT_ROUGHNESS_PERCENTILE = 100 / 3   # ... and smooth when its roughness is in the lowest third of the analysed area
FLAT_MIN_CELLS = 9            # a patch needs at least 3 x 3 cells' worth of ground
FLAT_FULL_SIZE_CELLS = 100    # a patch of this many cells (about 21 km2 at 463 m) earns the full size score
FLAT_MEDIUM_CELLS = 25        # 'medium' confidence needs a patch at least this big ...
FLAT_MEDIUM_MEAN_SLOPE_DEG = 3.0   # ... and this gentle on average

# -- high vantage points -------------------------------------------------------------------------------------
VANTAGE_WINDOW = 5            # a point must be the highest of a 5 x 5 block of valid cells
VANTAGE_CONTEXT = 11          # its prominence is measured against the median of the surrounding 11 x 11 block
VANTAGE_MIN_PROMINENCE_M = 25.0
VANTAGE_FULL_PROMINENCE_M = 200.0     # this much prominence earns the full score
VANTAGE_MEDIUM_PROMINENCE_M = 100.0
VANTAGE_MAX_SLOPE_DEG = 12.0  # the analysis' default steepness limit: a point on steeper ground is not offered

MAX_TARGETS = 5
_EIGHT = np.ones((3, 3), dtype=int)


@dataclass
class TerrainTargets:
    targets: list[ScienceTarget] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parameters: dict[str, object] = field(default_factory=dict)
    recipe: str = ""


def _centre(bounds: BoundingBox, shape: tuple[int, int], row: int, col: int) -> LonLat:
    """Longitude/latitude of a cell centre: the analysis grid is uniform in degrees across its bounds."""
    rows, cols = shape
    return LonLat(
        latitude_deg=bounds.north_deg - (row + 0.5) * (bounds.north_deg - bounds.south_deg) / rows,
        longitude_deg_east=bounds.west_deg_east + (col + 0.5) * (bounds.east_deg_east - bounds.west_deg_east) / cols,
    )


def _evidence(dataset_id: UUID, layer_id: UUID, source_uri: str | None, measured: list[str], rule: str, limits: list[str]) -> list[ScienceEvidence]:
    return [
        *(ScienceEvidence(dataset_id=dataset_id, layer_id=layer_id, statement=m, measured=True, source_uri=source_uri, limitations=limits) for m in measured),
        ScienceEvidence(dataset_id=dataset_id, layer_id=layer_id, statement=rule, measured=False, source_uri=source_uri, limitations=limits),
    ]


def _arrays(arrays: Mapping[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    z = np.asarray(arrays["elevation_m"], dtype=float)
    slope = np.asarray(arrays["slope_deg"], dtype=float)
    rough = np.asarray(arrays["roughness_m"], dtype=float)
    valid = np.asarray(arrays["valid"], dtype=bool) & np.isfinite(z)
    return z, slope, rough, valid


def find_flat_safe_sites(
    arrays: Mapping[str, np.ndarray], bounds: BoundingBox, grid: LocalGridMetadata, analysis_id: UUID, dataset_id: UUID,
    source_uri: str | None = None,
) -> TerrainTargets:
    z, slope, rough, valid = _arrays(arrays)
    out = TerrainTargets(recipe=RECIPE_FLAT, parameters={
        "slope_below_deg": FLAT_SLOPE_DEG, "roughness_percentile": round(FLAT_ROUGHNESS_PERCENTILE, 2), "min_cells": FLAT_MIN_CELLS})
    usable = valid & np.isfinite(slope) & np.isfinite(rough)
    if not usable.any():
        out.warnings.append("No cell has a defined slope and roughness, so no flat sites can be found.")
        return out
    rough_limit = float(np.percentile(rough[usable], FLAT_ROUGHNESS_PERCENTILE))
    out.parameters["roughness_limit_m"] = round(rough_limit, 3)
    candidate = usable & (slope < FLAT_SLOPE_DEG) & (rough <= rough_limit)
    labels, count = ndimage.label(candidate, structure=_EIGHT)
    cell_km2 = grid.pixel_size_x_m * grid.pixel_size_y_m / 1e6
    limits = [
        f"The grid cell is about {grid.pixel_size_x_m:.0f} x {grid.pixel_size_y_m:.0f} m: a site is a patch of cells, not a surveyed landing site.",
        "Rocks and craters smaller than a cell cannot be seen in this data.",
    ]
    layer_id = uuid5(analysis_id, "slope_deg")
    found = []
    for k in range(1, count + 1):
        rr, cc = np.nonzero(labels == k)
        if rr.size < FLAT_MIN_CELLS:
            continue
        cr, cc_ = rr.mean(), cc.mean()
        d2 = (rr - cr) ** 2 + (cc - cc_) ** 2
        best = int(np.lexsort((cc, rr, d2))[0])             # nearest to the centroid; ties go to the smaller row, then column
        row, col = int(rr[best]), int(cc[best])
        mean_slope, max_slope = float(slope[rr, cc].mean()), float(slope[rr, cc].max())
        size_score = min(1.0, rr.size / FLAT_FULL_SIZE_CELLS)
        flat_score = max(0.0, 1.0 - mean_slope / FLAT_SLOPE_DEG)
        score = round(0.6 * size_score + 0.4 * flat_score, 4)
        found.append((score, row, col, rr.size, mean_slope, max_slope, float(rough[rr, cc].mean()), float(z[rr, cc].min()), float(z[rr, cc].max())))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    if not found:
        out.warnings.append(f"No connected patch of at least {FLAT_MIN_CELLS} cells has slope under {FLAT_SLOPE_DEG:g} degrees and low roughness in this area. This is not a statement about smaller flat spots.")
        return out
    for rank, (score, row, col, n, ms, xs, mr, zlo, zhi) in enumerate(found[:MAX_TARGETS], start=1):
        medium = n >= FLAT_MEDIUM_CELLS and ms < FLAT_MEDIUM_MEAN_SLOPE_DEG
        out.targets.append(ScienceTarget(
            id=uuid5(analysis_id, f"{FLAT_SITES_ID}:{row}:{col}"), location=_centre(bounds, z.shape, row, col),
            title=f"Flat, smooth patch of {n} cells (about {n * cell_km2:.1f} km2)", objective_category=FLAT_SITES_ID,
            relevance_score=score, confidence="medium" if medium else "low",
            rank_explanation=(f"rank {rank} of {len(found)}; score = 0.6 x size ({n} of {FLAT_FULL_SIZE_CELLS} cells, capped at 1) + 0.4 x flatness "
                              f"(1 - mean slope {ms:.1f} / {FLAT_SLOPE_DEG:g} degrees). Confidence reflects the patch size and slope only."),
            evidence=_evidence(
                dataset_id, layer_id, source_uri,
                [f"Connected patch of {n} valid cells (about {n * cell_km2:.1f} km2) with mean slope {ms:.1f} degrees (maximum {xs:.1f}) and mean roughness {mr:.2f} m.",
                 f"Elevation over the patch runs from {zlo:.0f} to {zhi:.0f} m."],
                f"Rule: slope below {FLAT_SLOPE_DEG:g} degrees and roughness in the lowest third of the area ({rough_limit:.2f} m or less), "
                f"connected cells, at least {FLAT_MIN_CELLS} cells. A heuristic, not a published safety criterion.", limits),
        ))
    return out


def find_high_vantage_points(
    arrays: Mapping[str, np.ndarray], bounds: BoundingBox, grid: LocalGridMetadata, analysis_id: UUID, dataset_id: UUID,
    source_uri: str | None = None,
) -> TerrainTargets:
    z, slope, _rough, valid = _arrays(arrays)
    out = TerrainTargets(recipe=RECIPE_VANTAGE, parameters={
        "window_cells": VANTAGE_WINDOW, "context_cells": VANTAGE_CONTEXT, "min_prominence_m": VANTAGE_MIN_PROMINENCE_M, "max_slope_deg": VANTAGE_MAX_SLOPE_DEG})
    rows, cols = z.shape
    if rows < VANTAGE_WINDOW or cols < VANTAGE_WINDOW or not valid.any():
        out.warnings.append("The area is too small, or has too little elevation data, to find a local high point.")
        return out
    filled = np.where(valid, z, -np.inf)
    local_max = ndimage.maximum_filter(filled, size=VANTAGE_WINDOW, mode="constant", cval=-np.inf)
    half = VANTAGE_WINDOW // 2
    full_window = ndimage.minimum_filter(valid.astype(np.uint8), size=VANTAGE_WINDOW, mode="constant", cval=0).astype(bool)
    interior = np.zeros_like(valid)
    interior[half:rows - half, half:cols - half] = True
    peak = valid & full_window & interior & (z >= local_max)           # the highest of a fully valid 5 x 5 block
    labels, count = ndimage.label(peak, structure=_EIGHT)                # a flat top is one point, not many
    limits = [
        f"The grid cell is about {grid.pixel_size_x_m:.0f} x {grid.pixel_size_y_m:.0f} m: a point is the highest cell of a rise in a global model.",
        "Line of sight and radio visibility are not computed.",
    ]
    layer_id = uuid5(analysis_id, "elevation_m")
    found = []
    for k in range(1, count + 1):
        rr, cc = np.nonzero(labels == k)
        cr, cc_ = rr.mean(), cc.mean()
        best = int(np.lexsort((cc, rr, (rr - cr) ** 2 + (cc - cc_) ** 2))[0])
        row, col = int(rr[best]), int(cc[best])
        r0, r1 = max(0, row - VANTAGE_CONTEXT // 2), min(rows, row + VANTAGE_CONTEXT // 2 + 1)
        c0, c1 = max(0, col - VANTAGE_CONTEXT // 2), min(cols, col + VANTAGE_CONTEXT // 2 + 1)
        around = z[r0:r1, c0:c1][valid[r0:r1, c0:c1]]
        prominence = float(z[row, col] - np.median(around))
        s = float(slope[row, col]) if np.isfinite(slope[row, col]) else None
        if prominence < VANTAGE_MIN_PROMINENCE_M or s is None or s >= VANTAGE_MAX_SLOPE_DEG:
            continue
        found.append((prominence, row, col, float(z[row, col]), s, int(around.size)))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    if not found:
        out.warnings.append(f"No cell stands at least {VANTAGE_MIN_PROMINENCE_M:g} m above its surroundings on ground gentler than {VANTAGE_MAX_SLOPE_DEG:g} degrees in this area.")
        return out
    for rank, (prom, row, col, elev, s, n) in enumerate(found[:MAX_TARGETS], start=1):
        out.targets.append(ScienceTarget(
            id=uuid5(analysis_id, f"{VANTAGE_ID}:{row}:{col}"), location=_centre(bounds, z.shape, row, col),
            title=f"Local high point, {prom:.0f} m above its surroundings", objective_category=VANTAGE_ID,
            relevance_score=round(min(1.0, prom / VANTAGE_FULL_PROMINENCE_M), 4), confidence="medium" if prom >= VANTAGE_MEDIUM_PROMINENCE_M else "low",
            rank_explanation=(f"rank {rank} of {len(found)}; score = prominence {prom:.0f} m / {VANTAGE_FULL_PROMINENCE_M:g} m, capped at 1. "
                              "Confidence reflects the prominence only."),
            evidence=_evidence(
                dataset_id, layer_id, source_uri,
                [f"Elevation {elev:.0f} m, the highest of the surrounding {VANTAGE_WINDOW} x {VANTAGE_WINDOW} cells, {prom:.0f} m above the median of the {n} valid cells around it.",
                 f"Slope at the point is {s:.1f} degrees."],
                f"Rule: highest of a fully valid {VANTAGE_WINDOW} x {VANTAGE_WINDOW} block, at least {VANTAGE_MIN_PROMINENCE_M:g} m above the median of the "
                f"{VANTAGE_CONTEXT} x {VANTAGE_CONTEXT} block, slope under {VANTAGE_MAX_SLOPE_DEG:g} degrees. A heuristic ranking, not a survey.", limits),
        ))
    return out


DETECTORS = {FLAT_SITES_ID: find_flat_safe_sites, VANTAGE_ID: find_high_vantage_points}
