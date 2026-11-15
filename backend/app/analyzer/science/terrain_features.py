"""More terrain objectives: lowest ground, steep cliffs, ridges and craters.

Same approach as ``terrain_objectives.py``: pure functions over the elevation, slope and roughness arrays of a terrain bundle.
Nothing is downloaded and nothing is invented. Every target is a cell or a patch of the analysed grid, with its measured
values listed as measured and the rule that ranks it listed as a heuristic. The grid is 463 m wide, so only features that
are several cells across can be found.
"""
from __future__ import annotations

from typing import Mapping
from uuid import UUID, uuid5

import numpy as np
from scipy import ndimage

from app.schemas import BoundingBox, LocalGridMetadata, ScienceTarget

from .objectives import CLIFFS as CLIFFS_ID, CRATERS as CRATERS_ID, LOWEST as LOWEST_ID, RIDGES as RIDGES_ID
from .terrain_objectives import (
    DETECTORS as BASE_DETECTORS, MAX_TARGETS, VANTAGE_MAX_SLOPE_DEG, TerrainTargets, _EIGHT, _arrays, _centre, _evidence,
)

RECIPE_LOWEST, RECIPE_CLIFFS, RECIPE_RIDGES, RECIPE_CRATERS = "lowest-ground/1", "steep-cliffs/1", "ridges/1", "craters/1"
LOW_WINDOW, LOW_CONTEXT, LOW_MIN_DEPTH_M, LOW_FULL_DEPTH_M, LOW_MEDIUM_DEPTH_M = 5, 11, 25.0, 200.0, 100.0
CLIFF_SLOPE_DEG, CLIFF_MIN_CELLS, CLIFF_FULL_RELIEF_M, CLIFF_MEDIUM_CELLS = 15.0, 4, 500.0, 9
CONTEXT_CELLS = 15            # ridges and craters are judged against the mean of the surrounding 15 x 15 cells
RIDGE_MIN_HEIGHT_M, RIDGE_MIN_CELLS, RIDGE_MIN_ELONGATION, RIDGE_FULL_HEIGHT_M, RIDGE_MEDIUM_LENGTH_CELLS = 30.0, 6, 2.5, 150.0, 8
CRATER_MIN_DEPTH_M, CRATER_MIN_CELLS, CRATER_FULL_DEPTH_M, CRATER_MEDIUM_CELLS = 40.0, 9, 300.0, 25


def _context_mean(z: np.ndarray, valid: np.ndarray, size: int) -> np.ndarray:
    num = ndimage.uniform_filter(np.where(valid, z, 0.0), size=size, mode="constant")
    den = ndimage.uniform_filter(valid.astype(float), size=size, mode="constant")
    return np.where(den > 0.3, num / np.maximum(den, 1e-9), np.nan)


def _nearest_centroid(rr: np.ndarray, cc: np.ndarray) -> tuple[int, int]:
    cr, cc_ = rr.mean(), cc.mean()
    best = int(np.lexsort((cc, rr, (rr - cr) ** 2 + (cc - cc_) ** 2))[0])
    return int(rr[best]), int(cc[best])


def _limits(grid: LocalGridMetadata, what: str) -> list[str]:
    return [f"The grid cell is about {grid.pixel_size_x_m:.0f} x {grid.pixel_size_y_m:.0f} m: {what}", "Features smaller than a few cells cannot be seen in this data."]


def find_lowest_ground(
    arrays: Mapping[str, np.ndarray], bounds: BoundingBox, grid: LocalGridMetadata, analysis_id: UUID, dataset_id: UUID,
    source_uri: str | None = None,
) -> TerrainTargets:
    z, slope, _rough, valid = _arrays(arrays)
    out = TerrainTargets(recipe=RECIPE_LOWEST, parameters={
        "window_cells": LOW_WINDOW, "context_cells": LOW_CONTEXT, "min_depth_m": LOW_MIN_DEPTH_M, "max_slope_deg": VANTAGE_MAX_SLOPE_DEG})
    rows, cols = z.shape
    if rows < LOW_WINDOW or cols < LOW_WINDOW or not valid.any():
        out.warnings.append("The area is too small, or has too little elevation data, to find a local low point.")
        return out
    filled = np.where(valid, z, np.inf)
    local_min = ndimage.minimum_filter(filled, size=LOW_WINDOW, mode="constant", cval=np.inf)
    half = LOW_WINDOW // 2
    full_window = ndimage.minimum_filter(valid.astype(np.uint8), size=LOW_WINDOW, mode="constant", cval=0).astype(bool)
    interior = np.zeros_like(valid)
    interior[half:rows - half, half:cols - half] = True
    low = valid & full_window & interior & (z <= local_min)
    labels, count = ndimage.label(low, structure=_EIGHT)
    layer_id = uuid5(analysis_id, "elevation_m")
    limits = _limits(grid, "a point is the lowest cell of a dip in a global model.")
    found = []
    for k in range(1, count + 1):
        rr, cc = np.nonzero(labels == k)
        row, col = _nearest_centroid(rr, cc)
        r0, r1 = max(0, row - LOW_CONTEXT // 2), min(rows, row + LOW_CONTEXT // 2 + 1)
        c0, c1 = max(0, col - LOW_CONTEXT // 2), min(cols, col + LOW_CONTEXT // 2 + 1)
        around = z[r0:r1, c0:c1][valid[r0:r1, c0:c1]]
        depth = float(np.median(around) - z[row, col])
        s = float(slope[row, col]) if np.isfinite(slope[row, col]) else None
        if depth < LOW_MIN_DEPTH_M or s is None or s >= VANTAGE_MAX_SLOPE_DEG:
            continue
        found.append((depth, row, col, float(z[row, col]), s, int(around.size)))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    if not found:
        out.warnings.append(f"No cell sits at least {LOW_MIN_DEPTH_M:g} m below its surroundings on ground gentler than {VANTAGE_MAX_SLOPE_DEG:g} degrees in this area.")
        return out
    for rank, (depth, row, col, elev, s, n) in enumerate(found[:MAX_TARGETS], start=1):
        out.targets.append(ScienceTarget(
            id=uuid5(analysis_id, f"{LOWEST_ID}:{row}:{col}"), location=_centre(bounds, z.shape, row, col),
            title=f"Local low point, {depth:.0f} m below its surroundings", objective_category=LOWEST_ID,
            relevance_score=round(min(1.0, depth / LOW_FULL_DEPTH_M), 4), confidence="medium" if depth >= LOW_MEDIUM_DEPTH_M else "low",
            rank_explanation=f"rank {rank} of {len(found)}; score = depth {depth:.0f} m / {LOW_FULL_DEPTH_M:g} m, capped at 1. Confidence reflects the depth only.",
            evidence=_evidence(
                dataset_id, layer_id, source_uri,
                [f"Elevation {elev:.0f} m, the lowest of the surrounding {LOW_WINDOW} x {LOW_WINDOW} cells, {depth:.0f} m below the median of the {n} valid cells around it.",
                 f"Slope at the point is {s:.1f} degrees."],
                f"Rule: lowest of a fully valid {LOW_WINDOW} x {LOW_WINDOW} block, at least {LOW_MIN_DEPTH_M:g} m below the median of the {LOW_CONTEXT} x {LOW_CONTEXT} block, "
                f"slope under {VANTAGE_MAX_SLOPE_DEG:g} degrees. A heuristic ranking, not a survey.", limits),
        ))
    return out


def find_steep_cliffs(
    arrays: Mapping[str, np.ndarray], bounds: BoundingBox, grid: LocalGridMetadata, analysis_id: UUID, dataset_id: UUID,
    source_uri: str | None = None,
) -> TerrainTargets:
    z, slope, _rough, valid = _arrays(arrays)
    out = TerrainTargets(recipe=RECIPE_CLIFFS, parameters={"slope_at_least_deg": CLIFF_SLOPE_DEG, "min_cells": CLIFF_MIN_CELLS})
    steep = valid & np.isfinite(slope) & (slope >= CLIFF_SLOPE_DEG)
    labels, count = ndimage.label(steep, structure=_EIGHT)
    layer_id = uuid5(analysis_id, "slope_deg")
    limits = _limits(grid, "a cliff is a connected group of steep cells, not a surveyed escarpment.")
    found = []
    for k in range(1, count + 1):
        rr, cc = np.nonzero(labels == k)
        if rr.size < CLIFF_MIN_CELLS:
            continue
        row, col = _nearest_centroid(rr, cc)
        relief = float(z[rr, cc].max() - z[rr, cc].min())
        found.append((relief, row, col, int(rr.size), float(slope[rr, cc].mean()), float(slope[rr, cc].max())))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    if not found:
        out.warnings.append(f"No connected group of at least {CLIFF_MIN_CELLS} cells is steeper than {CLIFF_SLOPE_DEG:g} degrees in this area.")
        return out
    for rank, (relief, row, col, n, ms, xs) in enumerate(found[:MAX_TARGETS], start=1):
        out.targets.append(ScienceTarget(
            id=uuid5(analysis_id, f"{CLIFFS_ID}:{row}:{col}"), location=_centre(bounds, z.shape, row, col),
            title=f"Steep ground of {n} cells, dropping {relief:.0f} m", objective_category=CLIFFS_ID,
            relevance_score=round(min(1.0, relief / CLIFF_FULL_RELIEF_M), 4), confidence="medium" if n >= CLIFF_MEDIUM_CELLS else "low",
            rank_explanation=f"rank {rank} of {len(found)}; score = elevation change {relief:.0f} m / {CLIFF_FULL_RELIEF_M:g} m, capped at 1. Confidence reflects the size only.",
            evidence=_evidence(
                dataset_id, layer_id, source_uri,
                [f"Connected group of {n} cells steeper than {CLIFF_SLOPE_DEG:g} degrees (mean {ms:.1f}, maximum {xs:.1f}).",
                 f"Elevation changes by {relief:.0f} m across the group."],
                f"Rule: connected cells with slope of at least {CLIFF_SLOPE_DEG:g} degrees, at least {CLIFF_MIN_CELLS} cells. A heuristic, not a survey.", limits),
        ))
    return out


def find_ridges(
    arrays: Mapping[str, np.ndarray], bounds: BoundingBox, grid: LocalGridMetadata, analysis_id: UUID, dataset_id: UUID,
    source_uri: str | None = None,
) -> TerrainTargets:
    z, _slope, _rough, valid = _arrays(arrays)
    out = TerrainTargets(recipe=RECIPE_RIDGES, parameters={
        "context_cells": CONTEXT_CELLS, "min_height_m": RIDGE_MIN_HEIGHT_M, "min_cells": RIDGE_MIN_CELLS, "min_elongation": RIDGE_MIN_ELONGATION})
    ctx = _context_mean(z, valid, CONTEXT_CELLS)
    raised = valid & np.isfinite(ctx) & ((z - ctx) >= RIDGE_MIN_HEIGHT_M)
    labels, count = ndimage.label(raised, structure=_EIGHT)
    layer_id = uuid5(analysis_id, "elevation_m")
    limits = _limits(grid, "a ridge is a long raised area of cells, not a surveyed crest line.")
    found = []
    for k in range(1, count + 1):
        rr, cc = np.nonzero(labels == k)
        if rr.size < RIDGE_MIN_CELLS:
            continue
        eig = np.linalg.eigvalsh(np.cov(np.vstack([rr, cc]).astype(float)) + np.eye(2) * 1e-9)
        elongation, length = float(np.sqrt(eig[1] / eig[0])), float(4.0 * np.sqrt(eig[1]))
        if elongation < RIDGE_MIN_ELONGATION:
            continue
        row, col = _nearest_centroid(rr, cc)
        height = float((z[rr, cc] - ctx[rr, cc]).max())
        found.append((height, row, col, int(rr.size), length, elongation))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    if not found:
        out.warnings.append(f"No long, narrow rise at least {RIDGE_MIN_HEIGHT_M:g} m above its surroundings was found in this area.")
        return out
    for rank, (height, row, col, n, length, elong) in enumerate(found[:MAX_TARGETS], start=1):
        out.targets.append(ScienceTarget(
            id=uuid5(analysis_id, f"{RIDGES_ID}:{row}:{col}"), location=_centre(bounds, z.shape, row, col),
            title=f"Ridge about {length * grid.pixel_size_x_m / 1000:.1f} km long, up to {height:.0f} m high", objective_category=RIDGES_ID,
            relevance_score=round(min(1.0, height / RIDGE_FULL_HEIGHT_M), 4), confidence="medium" if length >= RIDGE_MEDIUM_LENGTH_CELLS else "low",
            rank_explanation=f"rank {rank} of {len(found)}; score = height {height:.0f} m / {RIDGE_FULL_HEIGHT_M:g} m, capped at 1. Confidence reflects the length only.",
            evidence=_evidence(
                dataset_id, layer_id, source_uri,
                [f"Connected raised area of {n} cells, about {length:.0f} cells long and {elong:.1f} times longer than wide.",
                 f"It stands up to {height:.0f} m above the mean of the {CONTEXT_CELLS} x {CONTEXT_CELLS} cells around."],
                f"Rule: cells at least {RIDGE_MIN_HEIGHT_M:g} m above the local mean, connected, at least {RIDGE_MIN_CELLS} cells and {RIDGE_MIN_ELONGATION:g} times longer than wide. "
                "A heuristic ranking, not a survey.", limits),
        ))
    return out


def find_craters(
    arrays: Mapping[str, np.ndarray], bounds: BoundingBox, grid: LocalGridMetadata, analysis_id: UUID, dataset_id: UUID,
    source_uri: str | None = None,
) -> TerrainTargets:
    z, _slope, _rough, valid = _arrays(arrays)
    out = TerrainTargets(recipe=RECIPE_CRATERS, parameters={"context_cells": CONTEXT_CELLS, "min_depth_m": CRATER_MIN_DEPTH_M, "min_cells": CRATER_MIN_CELLS})
    ctx = _context_mean(z, valid, CONTEXT_CELLS)
    bowl = valid & np.isfinite(ctx) & ((ctx - z) >= CRATER_MIN_DEPTH_M)
    labels, count = ndimage.label(bowl, structure=_EIGHT)
    layer_id = uuid5(analysis_id, "elevation_m")
    limits = _limits(grid, "a crater is a rimmed bowl of cells, so only large craters are found.")
    found = []
    for k in range(1, count + 1):
        mask = labels == k
        rr, cc = np.nonzero(mask)
        if rr.size < CRATER_MIN_CELLS:
            continue
        h, w = rr.max() - rr.min() + 1, cc.max() - cc.min() + 1
        if rr.size / (h * w) < 0.5 or not 0.5 <= h / w <= 2.0:        # roughly round, not a strip
            continue
        ring = ndimage.binary_dilation(mask, structure=_EIGHT, iterations=2) & ~mask & valid
        if ring.sum() < 6:
            continue
        floor = float(z[mask].mean())
        rim = float(np.median(z[ring]))
        if (z[ring] > floor + CRATER_MIN_DEPTH_M / 2).mean() < 0.5 or rim - floor < CRATER_MIN_DEPTH_M / 2:   # a raised rim must surround the bowl
            continue
        row, col = _nearest_centroid(rr, cc)
        found.append((rim - float(z[mask].min()), row, col, int(rr.size), float(max(h, w))))
    found.sort(key=lambda f: (-f[0], f[1], f[2]))
    if not found:
        out.warnings.append(f"No rimmed bowl at least {CRATER_MIN_DEPTH_M:g} m deep and {CRATER_MIN_CELLS} cells wide was found in this area.")
        return out
    for rank, (depth, row, col, n, span) in enumerate(found[:MAX_TARGETS], start=1):
        out.targets.append(ScienceTarget(
            id=uuid5(analysis_id, f"{CRATERS_ID}:{row}:{col}"), location=_centre(bounds, z.shape, row, col),
            title=f"Crater-like bowl about {span * grid.pixel_size_x_m / 1000:.1f} km across, {depth:.0f} m deep", objective_category=CRATERS_ID,
            relevance_score=round(min(1.0, depth / CRATER_FULL_DEPTH_M), 4), confidence="medium" if n >= CRATER_MEDIUM_CELLS else "low",
            rank_explanation=f"rank {rank} of {len(found)}; score = depth below the rim {depth:.0f} m / {CRATER_FULL_DEPTH_M:g} m, capped at 1. Confidence reflects the size only.",
            evidence=_evidence(
                dataset_id, layer_id, source_uri,
                [f"Bowl of {n} cells about {span:.0f} cells across, with higher ground around it.", f"The lowest point is {depth:.0f} m below the rim."],
                f"Rule: cells at least {CRATER_MIN_DEPTH_M:g} m below the mean of the {CONTEXT_CELLS} x {CONTEXT_CELLS} cells around, connected, at least {CRATER_MIN_CELLS} cells, "
                "roughly round, with higher ground on at least half of the surrounding ring. A heuristic ranking, not a survey.", limits),
        ))
    return out


DETECTORS = {
    **BASE_DETECTORS,
    LOWEST_ID: find_lowest_ground, CLIFFS_ID: find_steep_cliffs, RIDGES_ID: find_ridges, CRATERS_ID: find_craters,
}
