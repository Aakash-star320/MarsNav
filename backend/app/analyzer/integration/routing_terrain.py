"""Terrain access for the routing engine.

``load_routing_terrain`` returns the analyzer's verified arrays and grid for an analysis, after
checking the analysis exists, is finished, has the requested ``analysis_version`` and passes the
checksum. Routing builds its own ``RegionalGrid`` from this object; the analyzer does not depend on
routing code.

Coordinates: the local grid is an equirectangular projection on the 3,396,190 m Mars sphere with its
standard parallel and central meridian at the centre of ``bounds`` (see ``docs/TERRAIN_CONTRACT.md``).
x increases east and y north, in metres; row 0 is the northern edge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import numpy as np

from app.analyzer.preprocessing.terrain_bundle import SPHERE_RADIUS_M, TerrainManifest
from app.schemas import BoundingBox, LocalGridMetadata, LonLat


class TerrainAccessError(RuntimeError):
    """``code`` is one of: not_found, not_ready, version_mismatch, unavailable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Service(Protocol):
    def get_job(self, job_id: UUID): ...
    def get_result(self, job_id: UUID): ...
    def load_terrain(self, job_id: UUID): ...


@dataclass(frozen=True)
class RoutingTerrain:
    analysis_id: UUID
    analysis_version: str
    terrain_version: str
    sha256: str
    shape: tuple[int, int]
    bounds: BoundingBox
    grid: LocalGridMetadata
    elevation_m: np.ndarray       # float32, NaN where invalid
    slope_deg: np.ndarray         # float32, NaN where undefined
    roughness_m: np.ndarray       # float32, NaN where undefined
    valid: np.ndarray             # bool, True where elevation is usable
    source_id: np.ndarray         # uint8, index into ``sources``; 255 = none
    quality_flags: np.ndarray     # uint8 bit flags (see TERRAIN_CONTRACT.md)
    sources: list[dict[str, object]]
    limitations: list[str]

    @property
    def origin_lonlat(self) -> tuple[float, float]:
        """(latitude, longitude) of the projection origin (centre of the bounds)."""
        b = self.bounds
        return (b.north_deg + b.south_deg) / 2, (b.east_deg_east + b.west_deg_east) / 2

    def lonlat_to_xy(self, p: LonLat) -> tuple[float, float]:
        lat0, lon0 = self.origin_lonlat
        x = SPHERE_RADIUS_M * math.cos(math.radians(lat0)) * math.radians(p.longitude_deg_east - lon0)
        y = SPHERE_RADIUS_M * math.radians(p.latitude_deg - lat0)
        return x, y

    def xy_to_lonlat(self, x: float, y: float) -> LonLat:
        lat0, lon0 = self.origin_lonlat
        return LonLat(
            latitude_deg=lat0 + math.degrees(y / SPHERE_RADIUS_M),
            longitude_deg_east=lon0 + math.degrees(x / (SPHERE_RADIUS_M * math.cos(math.radians(lat0)))),
        )

    def lonlat_to_cell(self, p: LonLat) -> tuple[int, int] | None:
        """(row, col) of the cell containing ``p``, or None when outside the grid."""
        x, y = self.lonlat_to_xy(p)
        g = self.grid
        col = math.floor((x - g.origin_x_m) / g.pixel_size_x_m)
        row = math.floor((g.origin_y_m - y) / g.pixel_size_y_m)
        rows, cols = self.shape
        return (row, col) if 0 <= row < rows and 0 <= col < cols else None

    def cell_center_xy(self, row: int, col: int) -> tuple[float, float]:
        g = self.grid
        return g.origin_x_m + g.pixel_size_x_m * (col + 0.5), g.origin_y_m - g.pixel_size_y_m * (row + 0.5)

    def cell_center_lonlat(self, row: int, col: int) -> LonLat:
        return self.xy_to_lonlat(*self.cell_center_xy(row, col))

    def is_usable(self, row: int, col: int) -> bool:
        return bool(self.valid[row, col])


def build_routing_terrain(manifest: TerrainManifest, arrays: dict[str, np.ndarray], analysis_version: str) -> RoutingTerrain:
    return RoutingTerrain(
        analysis_id=manifest.analysis_id, analysis_version=analysis_version, terrain_version=manifest.terrain_version,
        sha256=manifest.sha256, shape=manifest.shape, bounds=manifest.bounds, grid=manifest.grid,
        elevation_m=arrays["elevation_m"], slope_deg=arrays["slope_deg"], roughness_m=arrays["roughness_m"],
        valid=arrays["valid"], source_id=arrays["source_id"], quality_flags=arrays["quality_flags"],
        sources=list(manifest.sources), limitations=list(manifest.limitations),
    )


def load_routing_terrain(service: _Service, analysis_id: UUID, analysis_version: str) -> RoutingTerrain:
    job = service.get_job(analysis_id)
    if job is None:
        raise TerrainAccessError("not_found", f"analysis {analysis_id} does not exist")
    if job.stage.value != "completed":
        raise TerrainAccessError("not_ready", f"analysis {analysis_id} is {job.stage.value}, not completed")
    result = service.get_result(analysis_id)
    if result is None:
        raise TerrainAccessError("unavailable", "the analysis result artifact is missing")
    if result.analysis_version != analysis_version:
        raise TerrainAccessError(
            "version_mismatch",
            f"requested analysis_version {analysis_version!r} but analysis {analysis_id} is {result.analysis_version!r}",
        )
    terrain = service.load_terrain(analysis_id)
    if terrain is None:
        raise TerrainAccessError("unavailable", "the terrain arrays are missing or failed verification")
    manifest, arrays = terrain
    return build_routing_terrain(manifest, arrays, result.analysis_version)
