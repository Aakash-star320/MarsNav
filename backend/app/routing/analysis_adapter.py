
from dataclasses import dataclass

import numpy as np
from pyproj import CRS

from app.analyzer.integration.routing_terrain import RoutingTerrain
from app.schemas import RegionalAnalysisResult

from .terrain import (
    GridContractError,
    GridSpec,
    RasterLayer,
    RegionalGrid,
    TerrainModel,
    analyze_terrain,
)


ARRAY_BY_KIND = {
    "elevation": "elevation_m",
    "slope": "slope_deg",
    "roughness": "roughness_m",
    "validity": "valid",
    "source": "source_id",
}

UNITS_BY_KIND = {
    "elevation": "m",
    "slope": "deg",
    "roughness": "m",
    "validity": "boolean",
    "source": "index",
}


@dataclass(frozen=True)
class AdaptedRoutingGrid:
    grid: RegionalGrid
    terrain_model: TerrainModel
    layer_ids: tuple[str, ...]
    quality_flags: np.ndarray
    source_id: np.ndarray
    warnings: tuple[str, ...]


def adapt_routing_terrain(
    routing: RoutingTerrain,
    result: RegionalAnalysisResult,
) -> AdaptedRoutingGrid:

    if result.id != routing.analysis_id:
        raise GridContractError("Analysis ID does not match terrain bundle")

    if result.analysis_version != routing.analysis_version:
        raise GridContractError("Analysis version does not match terrain bundle")

    rows, cols = routing.shape

    arrays = {
        "elevation_m": routing.elevation_m,
        "slope_deg": routing.slope_deg,
        "roughness_m": routing.roughness_m,
        "valid": routing.valid,
        "source_id": routing.source_id,
        "quality_flags": routing.quality_flags,
    }

    expected_dtypes = {
        "elevation_m": np.dtype("float32"),
        "slope_deg": np.dtype("float32"),
        "roughness_m": np.dtype("float32"),
        "valid": np.dtype("bool"),
        "source_id": np.dtype("uint8"),
        "quality_flags": np.dtype("uint8"),
    }

    for name, array in arrays.items():
        if array.shape != (rows, cols):
            raise GridContractError(f"{name} dimensions do not match terrain grid")
        if array.dtype != expected_dtypes[name]:
            raise GridContractError(f"{name} has an invalid dtype")

    valid = routing.valid

    if np.any(valid & ~np.isfinite(routing.elevation_m)):
        raise GridContractError("Valid cells must have finite elevation")

    metadata = routing.grid
    px = float(metadata.pixel_size_x_m)
    py = float(metadata.pixel_size_y_m)

    if not np.isfinite(px) or not np.isfinite(py) or px <= 0 or py <= 0:
        raise GridContractError("Invalid pixel dimensions")

    transform = tuple(float(v) for v in metadata.affine_transform)

    expected_transform = (
        px, 0.0, float(metadata.origin_x_m),
        0.0, -py, float(metadata.origin_y_m),
    )

    if len(transform) != 6 or not np.allclose(
        transform, expected_transform, atol=1e-6
    ):
        raise GridContractError("Affine transform does not match grid metadata")

    if not metadata.north_up or not metadata.raster_rows_increase_south:
        raise GridContractError("Unsupported raster orientation")

    try:
        crs = CRS.from_wkt(metadata.crs_wkt)
    except Exception as exc:
        raise GridContractError("Invalid terrain CRS WKT") from exc

    if not crs.is_projected:
        raise GridContractError("Routing requires a projected CRS")

    if len(crs.axis_info) < 2 or any(
        axis.unit_name.lower() not in {"metre", "meter"}
        for axis in crs.axis_info[:2]
    ):
        raise GridContractError("Routing CRS must use metres")

    spec = GridSpec(
        rows=rows,
        cols=cols,
        projection=metadata.crs_wkt,
        transform=transform,
        linear_unit_to_m=1.0,
    )

    layers_by_kind = {}

    for layer in result.layers:
        if layer.kind not in ARRAY_BY_KIND:
            continue

        if layer.kind in layers_by_kind:
            raise GridContractError(f"Duplicate {layer.kind} layer")

        if layer.units != UNITS_BY_KIND[layer.kind]:
            raise GridContractError(
                f"Invalid units for {layer.kind}: {layer.units}"
            )

        if layer.grid is not None:
            if layer.grid.crs_wkt != metadata.crs_wkt:
                raise GridContractError(
                    f"{layer.kind} layer CRS does not match terrain grid"
                )
            if not np.allclose(
                layer.grid.affine_transform, transform, atol=1e-6
            ):
                raise GridContractError(
                    f"{layer.kind} layer transform does not match terrain grid"
                )

        layers_by_kind[layer.kind] = layer

    missing = set(ARRAY_BY_KIND) - set(layers_by_kind)

    if missing:
        raise GridContractError(
            f"Missing terrain layer references: {sorted(missing)}"
        )

    raster_layers = {}

    for kind, array_name in ARRAY_BY_KIND.items():
        layer = layers_by_kind[kind]
        layer_id = str(layer.id)

        raster_layers[layer_id] = RasterLayer(
            layer_id=layer_id,
            values=arrays[array_name],
            projection=metadata.crs_wkt,
            transform=transform,
            valid_mask=valid if kind in {
                "elevation", "slope", "roughness"
            } else None,
            units=layer.units,
        )

    grid = RegionalGrid(
        grid_id=f"{routing.analysis_id}:{routing.terrain_version}",
        spec=spec,
        layers=raster_layers,
        valid_mask=valid,
    )

    elevation_id = str(layers_by_kind["elevation"].id)
    slope_id = str(layers_by_kind["slope"].id)
    roughness_id = str(layers_by_kind["roughness"].id)

    terrain_model = analyze_terrain(
        grid,
        elevation_layer_id=elevation_id,
        slope_layer_id=slope_id,
        roughness_layer_id=roughness_id,
        hazard_layer_id=None,
        require_hazard_layer=False,
    )

    warnings = list(routing.limitations)

    if np.any((routing.quality_flags & np.uint8(1)) != 0):
        warnings.append(
            "Coarse terrain resolution: individual rocks and small obstacles "
            "cannot be resolved."
        )

    warnings.append(
        "No hazard raster is currently available; hazard-free terrain "
        "cannot be certified."
    )

    layer_ids = tuple(str(layer.id) for layer in result.layers)

    return AdaptedRoutingGrid(
        grid=grid,
        terrain_model=terrain_model,
        layer_ids=layer_ids,
        quality_flags=routing.quality_flags,
        source_id=routing.source_id,
        warnings=tuple(dict.fromkeys(warnings)),
    )
