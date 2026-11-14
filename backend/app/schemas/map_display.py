"""Display payloads for the 2D/3D map (mirror of ``frontend/src/features/mars-map/types.ts``).

``MapLayerEntry`` wraps a canonical ``ProcessedLayer`` with display-only metadata; ``DemPayload`` is the
local-metre DEM the 3D view consumes. Neither replaces ``LocalGridMetadata`` or the terrain bundle.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import BoundingBox, ProcessedLayer


class DemProjection(BaseModel):
    kind: Literal["mars-local-equirectangular"] = "mars-local-equirectangular"
    radius_m: float = Field(gt=0)
    latitude_origin_deg: float = Field(ge=-90, le=90)
    longitude_origin_deg_east: float = Field(ge=-180, lt=180)


class DemPayload(BaseModel):
    version: Literal[1] = 1
    synthetic: bool
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    bounds: BoundingBox                     # extent of the sample points (not cell edges)
    projection: DemProjection
    affine: list[float] = Field(min_length=6, max_length=6)   # [x0, dx_col, dx_row, y0, dy_col, dy_row] in local metres
    sample_registration: Literal["point"] = "point"
    vertical_datum: str
    units: Literal["m"] = "m"
    values: list[float | None]              # row-major, north row first; null = no data


class MapLayerEntry(BaseModel):
    layer: ProcessedLayer
    projection: Literal["MARS:CANONICAL_ANGULAR"] = "MARS:CANONICAL_ANGULAR"
    format: Literal["image"] = "image"
    source: str
    synthetic: bool
    coverage: Literal["available", "partial", "unavailable", "unknown"]
    legend: str
    colors: list[str] = Field(min_length=2, max_length=2)


class RegionStatistics(BaseModel):
    """Descriptive statistics over valid cells at full analysis resolution (not a safety assessment)."""
    area_km2: float
    rows: int
    cols: int
    cells_total: int
    cells_valid: int
    valid_percent: float = Field(ge=0, le=100)
    native_resolution_m: float | None = None
    cell_size_x_m: float
    cell_size_y_m: float
    elevation_min_m: float | None = None
    elevation_max_m: float | None = None
    elevation_mean_m: float | None = None
    slope_mean_deg: float | None = None
    slope_max_deg: float | None = None
    slope_p50_deg: float | None = None
    slope_p90_deg: float | None = None
    slope_p99_deg: float | None = None
    roughness_mean_m: float | None = None
    roughness_max_m: float | None = None
    slope_limit_deg: float
    slope_denominator_cells: int
    slope_exceedance_cells: int
    slope_exceedance_fraction: float | None = None   # exceedance_cells / denominator_cells; None when no slope is defined
    science_candidates: int = 0
    notes: list[str] = Field(default_factory=list)


class MapPackage(BaseModel):
    analysis_id: str
    layers: list[MapLayerEntry]
    dem: DemPayload | None = None
    statistics: RegionStatistics | None = None
    notes: list[str] = Field(default_factory=list)
