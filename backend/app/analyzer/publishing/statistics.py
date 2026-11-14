"""Region statistics over valid cells (``valid`` mask), at full analysis resolution.

Unknown cells are reported separately and never counted as zero or flat. The slope-exceedance
fraction states its denominator. These are descriptive statistics of the source terrain, not a safety
assessment: a coarse grid cannot show rocks or small obstacles.
"""
from __future__ import annotations

import numpy as np

from app.analyzer.preprocessing.terrain_bundle import TerrainManifest
from app.schemas.map_display import RegionStatistics


def _stats(a: np.ndarray) -> tuple[float, float, float] | None:
    v = a[np.isfinite(a)]
    return (float(v.min()), float(v.max()), float(v.mean())) if v.size else None


def compute_statistics(manifest: TerrainManifest, arrays: dict[str, np.ndarray], slope_limit_deg: float = 12.0) -> RegionStatistics:
    rows, cols = manifest.shape
    g = manifest.grid
    valid = arrays["valid"]
    elev, slope, rough = arrays["elevation_m"], arrays["slope_deg"], arrays["roughness_m"]
    e, s, r = _stats(elev), _stats(slope), _stats(rough)
    sv = slope[np.isfinite(slope)]
    native = manifest.sources[0].get("native_resolution_m") if manifest.sources else None
    n_valid, n_total = int(valid.sum()), rows * cols
    notes = [
        "Statistics describe valid source cells only; missing cells are excluded and reported separately.",
        f"Cell size is {g.pixel_size_x_m:.0f} m x {g.pixel_size_y_m:.0f} m: individual rocks and small obstacles cannot be resolved.",
        "Slope above a limit marks steep terrain at this resolution. It is not a safety assessment.",
    ]
    return RegionStatistics(
        area_km2=cols * g.pixel_size_x_m * rows * g.pixel_size_y_m / 1e6, rows=rows, cols=cols,
        cells_total=n_total, cells_valid=n_valid, valid_percent=100.0 * n_valid / n_total if n_total else 0.0,
        native_resolution_m=float(native) if isinstance(native, (int, float)) else None,
        cell_size_x_m=g.pixel_size_x_m, cell_size_y_m=g.pixel_size_y_m,
        elevation_min_m=e[0] if e else None, elevation_max_m=e[1] if e else None, elevation_mean_m=e[2] if e else None,
        slope_mean_deg=s[2] if s else None, slope_max_deg=s[1] if s else None,
        slope_p50_deg=float(np.percentile(sv, 50)) if sv.size else None,
        slope_p90_deg=float(np.percentile(sv, 90)) if sv.size else None,
        slope_p99_deg=float(np.percentile(sv, 99)) if sv.size else None,
        roughness_mean_m=r[2] if r else None, roughness_max_m=r[1] if r else None,
        slope_limit_deg=slope_limit_deg, slope_denominator_cells=int(sv.size),
        slope_exceedance_cells=int((sv > slope_limit_deg).sum()),
        slope_exceedance_fraction=float((sv > slope_limit_deg).mean()) if sv.size else None,
        science_candidates=0, notes=notes,
    )
