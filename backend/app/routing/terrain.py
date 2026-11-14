from __future__ import annotations

from dataclasses import dataclass
from math import atan, degrees, hypot, isfinite, sqrt
from typing import Mapping, Sequence

Number = int | float
Cell = tuple[int, int]
Matrix = Sequence[Sequence[Number | None]]
Mask = Sequence[Sequence[bool]]


class GridContractError(ValueError):
    """Raised when regional layers do not match the canonical grid contract."""


@dataclass(frozen=True)
class GridSpec:
    rows: int
    cols: int
    projection: str
    transform: tuple[float, float, float, float, float, float]
    linear_unit_to_m: float = 1.0

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.cols <= 0:
            raise GridContractError("Grid rows and columns must be positive")
        if not self.projection.strip():
            raise GridContractError("Grid projection must be declared")
        if len(self.transform) != 6 or not all(isfinite(float(v)) for v in self.transform):
            raise GridContractError("Grid transform must contain six finite affine values")
        a, b, _, d, e, _ = self.transform
        if abs(a * e - b * d) < 1e-12:
            raise GridContractError("Grid transform is singular")
        if not isfinite(self.linear_unit_to_m) or self.linear_unit_to_m <= 0:
            raise GridContractError("linear_unit_to_m must be a positive finite value")

    def contains(self, cell: Cell) -> bool:
        row, col = cell
        return 0 <= row < self.rows and 0 <= col < self.cols

    def center_xy_m(self, cell: Cell) -> tuple[float, float]:
        row, col = cell
        if not self.contains(cell):
            raise IndexError(f"Cell outside grid: {cell}")
        a, b, c, d, e, f = self.transform
        pixel_col = col + 0.5
        pixel_row = row + 0.5
        x = (a * pixel_col + b * pixel_row + c) * self.linear_unit_to_m
        y = (d * pixel_col + e * pixel_row + f) * self.linear_unit_to_m
        return x, y

    def distance_m(self, first: Cell, second: Cell) -> float:
        x1, y1 = self.center_xy_m(first)
        x2, y2 = self.center_xy_m(second)
        return hypot(x2 - x1, y2 - y1)


@dataclass(frozen=True)
class RasterLayer:
    layer_id: str
    values: Matrix
    projection: str
    transform: tuple[float, float, float, float, float, float]
    valid_mask: Mask | None = None
    units: str = ""

    def value_at(self, row: int, col: int) -> float | None:
        value = self.values[row][col]
        if self.valid_mask is not None and not self.valid_mask[row][col]:
            return None
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if isfinite(numeric) else None


@dataclass(frozen=True)
class RegionalGrid:
    grid_id: str
    spec: GridSpec
    layers: Mapping[str, RasterLayer]
    valid_mask: Mask | None = None

    def __post_init__(self) -> None:
        if not self.grid_id.strip():
            raise GridContractError("grid_id must be non-empty")
        _validate_mask(self.valid_mask, self.spec.rows, self.spec.cols, "grid valid_mask")
        for key, layer in self.layers.items():
            if key != layer.layer_id:
                raise GridContractError(f"Layer key {key!r} does not match layer_id {layer.layer_id!r}")
            if layer.projection != self.spec.projection:
                raise GridContractError(f"Layer {key!r} projection does not match regional grid")
            if tuple(layer.transform) != tuple(self.spec.transform):
                raise GridContractError(f"Layer {key!r} transform does not match regional grid")
            _validate_matrix(layer.values, self.spec.rows, self.spec.cols, f"layer {key!r}")
            _validate_mask(layer.valid_mask, self.spec.rows, self.spec.cols, f"layer {key!r} valid_mask")

    def is_valid(self, row: int, col: int) -> bool:
        return self.valid_mask is None or bool(self.valid_mask[row][col])

    def get_layer(self, layer_id: str | None) -> RasterLayer | None:
        if layer_id is None:
            return None
        try:
            return self.layers[layer_id]
        except KeyError as exc:
            raise GridContractError(f"Required layer {layer_id!r} is not present in grid {self.grid_id!r}") from exc


@dataclass(frozen=True)
class TerrainCell:
    slope_deg: float | None
    roughness_m: float | None
    elevation_m: float | None
    is_hazard: bool
    hazard_severity: float
    unknown: bool
    unknown_reasons: tuple[str, ...]


@dataclass(frozen=True)
class TerrainModel:
    grid: RegionalGrid
    cells: tuple[tuple[TerrainCell, ...], ...]
    source_layer_ids: tuple[str, ...]
    formula_version: str = "terrain-v1"

    def at(self, cell: Cell) -> TerrainCell:
        row, col = cell
        if not self.grid.spec.contains(cell):
            raise IndexError(f"Cell outside grid: {cell}")
        return self.cells[row][col]


def _validate_matrix(values: Sequence[Sequence[object]], rows: int, cols: int, name: str) -> None:
    if len(values) != rows:
        raise GridContractError(f"{name} row count does not match grid")
    if any(len(row) != cols for row in values):
        raise GridContractError(f"{name} column count does not match grid")


def _validate_mask(mask: Mask | None, rows: int, cols: int, name: str) -> None:
    if mask is not None:
        _validate_matrix(mask, rows, cols, name)


def _sample(layer: RasterLayer | None, grid: RegionalGrid, row: int, col: int) -> float | None:
    if layer is None or not grid.is_valid(row, col):
        return None
    return layer.value_at(row, col)


def _solve_plane(points: list[tuple[float, float, float]]) -> tuple[float, float] | None:
    """Least-squares local plane z = gx*x + gy*y + c."""
    if len(points) < 3:
        return None
    n = float(len(points))
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sz = sum(p[2] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    syy = sum(p[1] * p[1] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    sxz = sum(p[0] * p[2] for p in points)
    syz = sum(p[1] * p[2] for p in points)

    # Centering reduces the plane fit to a 2x2 system.
    mean_x, mean_y, mean_z = sx / n, sy / n, sz / n
    xx = sxx - sx * mean_x
    yy = syy - sy * mean_y
    xy = sxy - sx * mean_y
    xz = sxz - sx * mean_z
    yz = syz - sy * mean_z
    determinant = xx * yy - xy * xy
    if abs(determinant) < 1e-12:
        return None
    gx = (xz * yy - yz * xy) / determinant
    gy = (yz * xx - xz * xy) / determinant
    return gx, gy


def _derive_slope(elevation: RasterLayer, grid: RegionalGrid, row: int, col: int) -> float | None:
    center = _sample(elevation, grid, row, col)
    if center is None:
        return None
    origin_x, origin_y = grid.spec.center_xy_m((row, col))
    points: list[tuple[float, float, float]] = [(0.0, 0.0, center)]
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            neighbour = (row + dr, col + dc)
            if not grid.spec.contains(neighbour):
                continue
            value = _sample(elevation, grid, neighbour[0], neighbour[1])
            if value is None:
                continue
            x, y = grid.spec.center_xy_m(neighbour)
            points.append((x - origin_x, y - origin_y, value))
    gradient = _solve_plane(points)
    if gradient is None:
        return None
    return degrees(atan(sqrt(gradient[0] ** 2 + gradient[1] ** 2)))


def _derive_roughness(elevation: RasterLayer, grid: RegionalGrid, row: int, col: int) -> float | None:
    values: list[float] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            neighbour = (row + dr, col + dc)
            if not grid.spec.contains(neighbour):
                continue
            value = _sample(elevation, grid, neighbour[0], neighbour[1])
            if value is not None:
                values.append(value)
    if len(values) < 2:
        return None
    # DEM elevation range is a roughness proxy only; it is not rock detection.
    return max(values) - min(values)


def analyze_terrain(
    grid: RegionalGrid,
    *,
    elevation_layer_id: str | None,
    slope_layer_id: str | None = None,
    roughness_layer_id: str | None = None,
    hazard_layer_id: str | None = None,
    require_hazard_layer: bool = True,
) -> TerrainModel:
    """Build terrain metrics from declared layers; never infer rock from a DEM."""
    elevation = grid.get_layer(elevation_layer_id)
    slope = grid.get_layer(slope_layer_id)
    roughness = grid.get_layer(roughness_layer_id)
    hazard = grid.get_layer(hazard_layer_id)
    source_ids = tuple(
        layer.layer_id for layer in (elevation, slope, roughness, hazard) if layer is not None
    )

    output: list[tuple[TerrainCell, ...]] = []
    for row in range(grid.spec.rows):
        row_cells: list[TerrainCell] = []
        for col in range(grid.spec.cols):
            elevation_value = _sample(elevation, grid, row, col)
            slope_value = _sample(slope, grid, row, col)
            if slope_value is None and elevation is not None:
                slope_value = _derive_slope(elevation, grid, row, col)

            roughness_value = _sample(roughness, grid, row, col)
            if roughness_value is None and elevation is not None and roughness is None:
                roughness_value = _derive_roughness(elevation, grid, row, col)

            hazard_value = _sample(hazard, grid, row, col)
            reasons: list[str] = []
            if not grid.is_valid(row, col):
                reasons.append("outside_valid_mask")
            if slope_value is None:
                reasons.append("slope_unknown")
            if roughness_value is None:
                reasons.append("roughness_unknown")
            if require_hazard_layer and (hazard is None or hazard_value is None):
                reasons.append("hazard_unknown")

            severity = 0.0 if hazard_value is None else max(0.0, min(1.0, hazard_value))
            is_hazard = hazard_value is not None and hazard_value > 0.0
            row_cells.append(
                TerrainCell(
                    slope_deg=slope_value,
                    roughness_m=roughness_value,
                    elevation_m=elevation_value,
                    is_hazard=is_hazard,
                    hazard_severity=severity,
                    unknown=bool(reasons),
                    unknown_reasons=tuple(reasons),
                )
            )
        output.append(tuple(row_cells))

    return TerrainModel(grid=grid, cells=tuple(output), source_layer_ids=source_ids)
