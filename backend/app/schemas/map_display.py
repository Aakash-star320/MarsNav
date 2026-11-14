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


class MapPackage(BaseModel):
    analysis_id: str
    layers: list[MapLayerEntry]
    dem: DemPayload | None = None
    notes: list[str] = Field(default_factory=list)
