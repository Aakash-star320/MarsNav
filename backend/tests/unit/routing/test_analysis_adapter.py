
from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from pyproj import CRS

from app.analyzer.integration.routing_terrain import RoutingTerrain
from app.routing.analysis_adapter import adapt_routing_terrain
from app.routing.terrain import GridContractError
from app.schemas import (
    BoundingBox,
    LocalGridMetadata,
    ProcessedLayer,
    RegionalAnalysisResult,
    RegionOfInterest,
)


def make_inputs():
    rows, cols = 4, 5
    px, py = 439.0, 463.0

    bounds = BoundingBox(
        west_deg_east=10,
        south_deg=20,
        east_deg_east=11,
        north_deg=21,
    )

    crs_wkt = CRS.from_epsg(3857).to_wkt()

    origin_x = -(cols * px) / 2
    origin_y = (rows * py) / 2

    transform = [
        px, 0.0, origin_x,
        0.0, -py, origin_y,
    ]

    grid = LocalGridMetadata(
        crs_wkt=crs_wkt,
        affine_transform=transform,
        pixel_size_x_m=px,
        pixel_size_y_m=py,
        origin_x_m=origin_x,
        origin_y_m=origin_y,
        north_up=True,
        raster_rows_increase_south=True,
        body_name="Mars",
    )

    shape = (rows, cols)
    elevation = np.arange(rows * cols, dtype=np.float32).reshape(shape)
    slope = np.full(shape, 2.0, dtype=np.float32)
    roughness = np.full(shape, 0.5, dtype=np.float32)
    valid = np.ones(shape, dtype=bool)
    source_id = np.zeros(shape, dtype=np.uint8)
    quality_flags = np.ones(shape, dtype=np.uint8)

    arrays = {
        "elevation": "elevation_m",
        "slope": "slope_deg",
        "roughness": "roughness_m",
        "validity": "valid",
        "source": "source_id",
    }

    units = {
        "elevation": "m",
        "slope": "deg",
        "roughness": "m",
        "validity": "boolean",
        "source": "index",
    }

    layers = [
        ProcessedLayer(
            id=uuid4(),
            kind=kind,
            uri=f"test/terrain.npz#{arrays[kind]}",
            bounds=bounds,
            resolution_m_per_px=463.09,
            valid_percent=100.0,
            units=units[kind],
            dataset_ids=[],
            grid=grid,
        )
        for kind in arrays
    ]

    analysis_id = uuid4()
    mission_id = uuid4()

    result = RegionalAnalysisResult(
        id=analysis_id,
        mission_id=mission_id,
        roi=RegionOfInterest(
            name="Adapter test",
            bounds=bounds,
        ),
        projection_wkt=crs_wkt,
        grid=grid,
        datasets=[],
        layers=layers,
        science_targets=[],
        analysis_version="analysis/1",
    )

    routing = RoutingTerrain(
        analysis_id=analysis_id,
        analysis_version="analysis/1",
        terrain_version="terrain-bundle/1",
        sha256="a" * 64,
        shape=shape,
        bounds=bounds,
        grid=grid,
        elevation_m=elevation,
        slope_deg=slope,
        roughness_m=roughness,
        valid=valid,
        source_id=source_id,
        quality_flags=quality_flags,
        sources=[{"product_id": "test-mola"}],
        limitations=["Coarse terrain resolution"],
    )

    return routing, result, px, py


def test_adapter_builds_regional_grid():
    routing, result, px, py = make_inputs()

    adapted = adapt_routing_terrain(routing, result)

    assert adapted.grid.spec.rows == 4
    assert adapted.grid.spec.cols == 5
    assert adapted.grid.spec.linear_unit_to_m == 1.0

    assert adapted.grid.spec.distance_m(
        (0, 0), (1, 1)
    ) == pytest.approx(np.hypot(px, py))

    cell = adapted.terrain_model.at((0, 0))

    assert cell.slope_deg == pytest.approx(2.0)
    assert cell.roughness_m == pytest.approx(0.5)

    assert len(adapted.layer_ids) == 5
    assert adapted.quality_flags[0, 0] == 1

    assert any("Coarse" in warning for warning in adapted.warnings)
    assert any("hazard" in warning.lower() for warning in adapted.warnings)


def test_adapter_rejects_wrong_analysis_id():
    routing, result, _, _ = make_inputs()

    bad_result = result.model_copy(update={"id": uuid4()})

    with pytest.raises(GridContractError):
        adapt_routing_terrain(routing, bad_result)


def test_adapter_rejects_wrong_analysis_version():
    routing, result, _, _ = make_inputs()

    bad_result = result.model_copy(
        update={"analysis_version": "analysis/999"}
    )

    with pytest.raises(GridContractError):
        adapt_routing_terrain(routing, bad_result)


def test_adapter_rejects_wrong_array_shape():
    routing, result, _, _ = make_inputs()

    bad_routing = replace(
        routing,
        elevation_m=np.zeros((3, 5), dtype=np.float32),
    )

    with pytest.raises(GridContractError):
        adapt_routing_terrain(bad_routing, result)


def test_adapter_rejects_invalid_elevation():
    routing, result, _, _ = make_inputs()

    elevation = routing.elevation_m.copy()
    elevation[0, 0] = np.nan

    bad_routing = replace(routing, elevation_m=elevation)

    with pytest.raises(GridContractError):
        adapt_routing_terrain(bad_routing, result)


def test_adapter_rejects_missing_layer_reference():
    routing, result, _, _ = make_inputs()

    bad_result = result.model_copy(
        update={"layers": result.layers[:-1]}
    )

    with pytest.raises(GridContractError):
        adapt_routing_terrain(routing, bad_result)


def test_adapter_rejects_invalid_crs():
    routing, result, _, _ = make_inputs()

    bad_grid = routing.grid.model_copy(
        update={"crs_wkt": "not-a-valid-wkt"}
    )

    bad_routing = replace(routing, grid=bad_grid)

    with pytest.raises(GridContractError):
        adapt_routing_terrain(bad_routing, result)
