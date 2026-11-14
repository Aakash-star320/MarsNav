"""Terrain derivatives from a metric DEM grid.

Grids are ``(rows, cols)`` float arrays in metres. ``valid`` is a boolean mask; invalid cells never
contribute and never produce fake gradients. Row 0 is the northern edge when ``rows_increase_south``
is true (north-up rasters). Pixel spacing must be the real metric spacing of the grid.

* slope_deg   = degrees(atan(sqrt(dz/dx^2 + dz/dy^2))) using central differences where both
  neighbours are valid, one-sided differences where only one is valid, otherwise invalid.
* edge_grade  = (z_next - z_current) / horizontal_distance (signed, directional).
* roughness   = standard deviation of elevation within a (2k+1)^2 window of valid cells
  (a roughness proxy at an explicit scale; it is not the same as steepness).
"""
from __future__ import annotations

import numpy as np


def _axis_gradient(z: np.ndarray, valid: np.ndarray, spacing: float, axis: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell derivative along ``axis`` and a mask of cells where it is defined."""
    z0 = np.where(valid, z, 0.0)
    fwd_z, back_z = np.roll(z0, -1, axis), np.roll(z0, 1, axis)
    fwd_v, back_v = np.roll(valid, -1, axis), np.roll(valid, 1, axis)
    edge = np.zeros(z.shape, dtype=bool)
    edge_slice = [slice(None)] * 2
    edge_slice[axis] = -1
    edge[tuple(edge_slice)] = True      # roll wrapped around: no forward neighbour
    fwd_v = fwd_v & ~edge
    edge = np.zeros(z.shape, dtype=bool)
    edge_slice[axis] = 0
    edge[tuple(edge_slice)] = True      # no backward neighbour
    back_v = back_v & ~edge
    d = np.zeros(z.shape)
    both = valid & fwd_v & back_v
    d[both] = (fwd_z[both] - back_z[both]) / (2 * spacing)
    only_f = valid & fwd_v & ~back_v
    d[only_f] = (fwd_z[only_f] - z0[only_f]) / spacing
    only_b = valid & back_v & ~fwd_v
    d[only_b] = (z0[only_b] - back_z[only_b]) / spacing
    return d, valid & (fwd_v | back_v)


def slope_deg(z: np.ndarray, valid: np.ndarray, pixel_size_x_m: float, pixel_size_y_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope magnitude in degrees and its validity mask (NaN where undefined)."""
    if pixel_size_x_m <= 0 or pixel_size_y_m <= 0:
        raise ValueError("pixel sizes must be positive metres")
    valid = valid & np.isfinite(z)
    dzdx, vx = _axis_gradient(z, valid, pixel_size_x_m, axis=1)
    dzdy, vy = _axis_gradient(z, valid, pixel_size_y_m, axis=0)
    out_valid = vx & vy
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    return np.where(out_valid, slope, np.nan), out_valid


def edge_grade(z: np.ndarray, valid: np.ndarray, pixel_size_x_m: float, pixel_size_y_m: float, d_row: int, d_col: int) -> tuple[np.ndarray, np.ndarray]:
    """Signed grade moving by (d_row, d_col) cells: positive is uphill. NaN where either end is invalid."""
    if (d_row, d_col) == (0, 0) or max(abs(d_row), abs(d_col)) > 1:
        raise ValueError("move must be a unit step to one of the 8 neighbours")
    valid = valid & np.isfinite(z)
    dist = float(np.hypot(d_col * pixel_size_x_m, d_row * pixel_size_y_m))
    rows, cols = z.shape
    grade = np.full(z.shape, np.nan)
    ok = np.zeros(z.shape, dtype=bool)
    r0, r1 = max(0, -d_row), rows - max(0, d_row)
    c0, c1 = max(0, -d_col), cols - max(0, d_col)
    src = (slice(r0, r1), slice(c0, c1))
    dst = (slice(r0 + d_row, r1 + d_row), slice(c0 + d_col, c1 + d_col))
    both = valid[src] & valid[dst]
    grade[src] = np.where(both, (z[dst] - z[src]) / dist, np.nan)
    ok[src] = both
    return grade, ok


def roughness_std(z: np.ndarray, valid: np.ndarray, half_window: int = 1, min_valid_fraction: float = 0.6) -> tuple[np.ndarray, np.ndarray]:
    """Standard deviation of elevation in a (2k+1)^2 window; masked when too few valid cells."""
    if half_window < 1:
        raise ValueError("half_window must be >= 1")
    valid = valid & np.isfinite(z)
    k = half_window
    rows, cols = z.shape
    pv = np.pad(valid.astype(float), k)
    pz = np.pad(np.where(valid, z, 0.0), k)
    n = np.zeros(z.shape); s = np.zeros(z.shape); s2 = np.zeros(z.shape)
    for dr in range(2 * k + 1):
        for dc in range(2 * k + 1):
            win = (slice(dr, dr + rows), slice(dc, dc + cols))
            n += pv[win]; s += pz[win]; s2 += pz[win] ** 2
    window = (2 * half_window + 1) ** 2
    ok = valid & (n >= min_valid_fraction * window) & (n >= 2)
    mean = np.divide(s, n, out=np.zeros_like(s), where=n > 0)
    var = np.maximum(np.divide(s2, n, out=np.zeros_like(s2), where=n > 0) - mean ** 2, 0.0)
    return np.where(ok, np.sqrt(var), np.nan), ok
