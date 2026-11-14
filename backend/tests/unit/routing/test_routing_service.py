from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from pyproj import CRS

from app.analyzer.integration.routing_terrain import RoutingTerrain
from app.routing import service as routing_service
from app.routing.analysis_adapter import adapt_routing_terrain
from app.routing.costs import build_cost_model
from app.routing.pathfinding import _heuristic, find_path
from app.routing.request_adapter import adapt_route_request
from app.routing.feasibility import plan_mission
from app.schemas import (BoundingBox, LocalGridMetadata, ProcessedLayer, RegionalAnalysisResult,
    RegionOfInterest, RouteRequest, MissionConstraints, ScienceTarget, LonLat)


class StubAnalysis:
    def __init__(self, result, terrain):
        self.result, self.terrain = result, terrain

    def get_job(self, _):
        return type("Job", (), {"stage": type("Stage", (), {"value": "completed"})()})()

    def get_result(self, _):
        return self.result

    def load_terrain(self, _):
        raise AssertionError("service must use load_routing_terrain adapter")


@pytest.fixture
def scene(monkeypatch):
    rows = cols = 6
    bounds = BoundingBox(west_deg_east=9, south_deg=19, east_deg_east=11, north_deg=21)
    crs = CRS.from_epsg(3857).to_wkt()
    px, py = 100.0, 120.0
    ox, oy = -cols * px / 2, rows * py / 2
    grid = LocalGridMetadata(crs_wkt=crs, affine_transform=[px, 0, ox, 0, -py, oy],
        pixel_size_x_m=px, pixel_size_y_m=py, origin_x_m=ox, origin_y_m=oy,
        north_up=True, raster_rows_increase_south=True, body_name="Mars")
    aid, mid = uuid4(), uuid4()
    shape = (rows, cols)
    elevation = np.zeros(shape, np.float32)
    slope = np.full(shape, 2, np.float32)
    roughness = np.full(shape, .5, np.float32)
    valid = np.ones(shape, bool)
    arrays = {"elevation_m": elevation, "slope_deg": slope, "roughness_m": roughness,
        "valid": valid, "source_id": np.zeros(shape, np.uint8), "quality_flags": np.zeros(shape, np.uint8)}
    routing = RoutingTerrain(analysis_id=aid, analysis_version="analysis/1", terrain_version="terrain/1",
        sha256="a" * 64, shape=shape, bounds=bounds, grid=grid, elevation_m=elevation,
        slope_deg=slope, roughness_m=roughness, valid=valid, source_id=arrays["source_id"],
        quality_flags=arrays["quality_flags"], sources=[], limitations=[])
    kinds = [("elevation", "m", "elevation_m"), ("slope", "deg", "slope_deg"),
        ("roughness", "m", "roughness_m"), ("validity", "boolean", "valid"), ("source", "index", "source_id")]
    layers = [ProcessedLayer(id=uuid4(), kind=kind, uri=f"local#{key}", bounds=bounds,
        resolution_m_per_px=100, valid_percent=100, units=units, dataset_ids=[], grid=grid)
        for kind, units, key in kinds]
    result = RegionalAnalysisResult(id=aid, mission_id=mid,
        roi=RegionOfInterest(name="synthetic", bounds=bounds), projection_wkt=crs, grid=grid,
        datasets=[], layers=layers, science_targets=[], analysis_version="analysis/1")
    provider = StubAnalysis(result, routing)
    monkeypatch.setattr(routing_service, "load_routing_terrain", lambda svc, analysis_id, version: routing)

    def request(start=(1, 1), destination=(4, 4), **constraints):
        return RouteRequest(mission_id=mid, analysis_id=aid, analysis_version="analysis/1",
            start=routing.cell_center_lonlat(*start), destination=routing.cell_center_lonlat(*destination),
            constraints=MissionConstraints(**constraints))
    return routing, result, provider, request


def test_valid_route_distance_and_provenance(scene):
    routing, result, provider, request = scene
    planned = routing_service.plan_route(request(return_to_base=False), provider)
    assert planned.feasible and planned.route_cells[0] == (1, 1) and planned.route_cells[-1] == (4, 4)
    assert planned.distance_m == pytest.approx(3 * np.hypot(100, 120))
    assert planned.analysis_id == result.id and planned.analysis_version == result.analysis_version
    assert planned.layer_ids == tuple(str(layer.id) for layer in result.layers)
    assert "+" in planned.formula_version
    assert planned.terrain_version == routing.terrain_version
    assert planned.terrain_sha256 == routing.sha256


def test_unreachable_destination_returns_conflict(scene):
    routing, _, provider, request = scene
    valid = routing.valid.copy(); valid[4, 4] = False
    elevation = routing.elevation_m.copy(); elevation[4, 4] = np.nan
    routing_bad = replace(routing, valid=valid, elevation_m=elevation)
    monkeypatch_loader = routing_service.load_routing_terrain
    routing_service.load_routing_terrain = lambda *_: routing_bad
    try:
        result = routing_service.plan_route(request(return_to_base=False), provider)
    finally:
        routing_service.load_routing_terrain = monkeypatch_loader
    assert not result.feasible and not result.route_cells
    assert "unknown_terrain" in result.constraint_conflicts
    assert result.distance_m is result.estimated_duration_min is None
    assert result.max_slope_deg is result.elevation_gain_m is None


@pytest.mark.parametrize("which", ["start", "destination"])
def test_outside_coordinates_are_rejected(scene, which):
    routing, _, provider, request = scene
    req = request(return_to_base=False)
    bad_point = LonLat(latitude_deg=80, longitude_deg_east=80)
    req = req.model_copy(update={which: bad_point})
    result = routing_service.plan_route(req, provider)
    assert not result.feasible and result.constraint_conflicts[0].endswith("outside_grid")


def test_invalid_terrain_cannot_be_traversed(scene):
    routing, _, provider, request = scene
    valid = routing.valid.copy(); valid[2, 2] = False
    elevation = routing.elevation_m.copy(); elevation[2, 2] = np.nan
    bad = replace(routing, valid=valid, elevation_m=elevation)
    original = routing_service.load_routing_terrain
    routing_service.load_routing_terrain = lambda *_: bad
    try:
        result = routing_service.plan_route(request(destination=(2, 2), return_to_base=False), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert not result.feasible and "unknown_terrain" in result.constraint_conflicts


def test_max_slope_is_a_hard_constraint(scene):
    routing, _, provider, request = scene
    slope = routing.slope_deg.copy(); slope[2, 2] = 20
    bad = replace(routing, slope_deg=slope)
    original = routing_service.load_routing_terrain; routing_service.load_routing_terrain = lambda *_: bad
    try:
        result = routing_service.plan_route(request(start=(2, 1), destination=(2, 2), return_to_base=False,
            max_slope_deg=10), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert not result.feasible and "max_slope_exceeded" in result.constraint_conflicts


@pytest.mark.parametrize("policy,expected", [("exclude", False), ("penalize", True)])
def test_unknown_policy_exclude_or_penalize(scene, policy, expected):
    routing, _, provider, request = scene
    roughness = routing.roughness_m.copy(); roughness[2, 2] = np.nan
    bad = replace(routing, roughness_m=roughness)
    original = routing_service.load_routing_terrain; routing_service.load_routing_terrain = lambda *_: bad
    try:
        result = routing_service.plan_route(request(start=(2, 1), destination=(2, 2), return_to_base=False,
            unknown_terrain_policy=policy), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert result.feasible is expected
    if expected:
        assert result.route_cells[-1] == (2, 2)


def test_return_to_base_is_part_of_route(scene):
    _, _, provider, request = scene
    result = routing_service.plan_route(request(start=(1, 1), destination=(3, 3), return_to_base=True), provider)
    assert result.feasible and result.route_cells[0] == result.route_cells[-1] == (1, 1)
    assert result.distance_m == pytest.approx(2 * 2 * np.hypot(100, 120))


def test_reserve_is_applied_once_and_boundary_budget_is_feasible(scene):
    _, _, provider, request = scene
    route_length = 2 * 2 * np.hypot(100, 120)
    budget = route_length / .8
    result = routing_service.plan_route(request(start=(1, 1), destination=(3, 3), return_to_base=True,
        max_distance_m=budget, reserve_fraction=.2), provider)
    assert result.feasible and result.distance_m == pytest.approx(route_length)


def test_return_leg_is_included_in_duration_and_ascent_gain(scene):
    routing, _, provider, request = scene
    elevations = routing.elevation_m.copy(); elevations[3, 3] = 10
    bad = replace(routing, elevation_m=elevations)
    original = routing_service.load_routing_terrain; routing_service.load_routing_terrain = lambda *_: bad
    try:
        result = routing_service.plan_route(request(start=(1, 1), destination=(3, 3), return_to_base=True,
            traversal_speed_m_per_min=10, examination_time_per_target_min=0), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert result.feasible
    assert result.distance_m == pytest.approx(4 * np.hypot(100, 120))
    assert result.estimated_duration_min == pytest.approx(result.distance_m / 10)
    assert result.elevation_gain_m == pytest.approx(10)


def test_distance_budget_includes_return_and_reserve(scene):
    routing, analysis, provider, request = scene
    api_request = request(start=(1, 1), destination=(3, 3), return_to_base=True,
        max_distance_m=500, reserve_fraction=.2)
    result = routing_service.plan_route(api_request, provider)
    assert not result.feasible and "max_route_distance_exceeded" in result.constraint_conflicts
    adapted_grid = adapt_routing_terrain(routing, analysis)
    adapted = adapt_route_request(api_request, start=(1, 1), goal=(3, 3), base=(1, 1))
    costs = build_cost_model(adapted_grid.terrain_model, adapted.preferences, adapted.limits)
    engine_result = plan_mission(adapted_grid.terrain_model, costs, adapted.request, adapted.limits)
    assert engine_result.status == "infeasible"
    assert engine_result.path_cells == () and engine_result.distance_m is None
    assert engine_result.to_dict()["metrics"]["distance_m"] is None


def test_duration_budget_violation(scene):
    _, _, provider, request = scene
    result = routing_service.plan_route(request(start=(1, 1), destination=(3, 3), return_to_base=False,
        max_duration_min=1, traversal_speed_m_per_min=1), provider)
    assert not result.feasible and "max_duration_exceeded" in result.constraint_conflicts
    assert result.distance_m is result.estimated_duration_min is None


def test_required_targets_are_visited_in_request_order(scene):
    routing, analysis, provider, request = scene
    first, second = uuid4(), uuid4()
    analysis.science_targets = [
        ScienceTarget(id=first, location=routing.cell_center_lonlat(2, 1), title="first", objective_category="x",
            relevance_score=.5, confidence="unknown", evidence=[]),
        ScienceTarget(id=second, location=routing.cell_center_lonlat(2, 3), title="second", objective_category="x",
            relevance_score=.5, confidence="unknown", evidence=[]),
    ]
    req = request(return_to_base=False, required_target_ids=[first, second])
    planned = routing_service.plan_route(req, provider)
    assert planned.feasible and planned.target_ids == (first, second)
    assert planned.route_cells.index((2, 1)) < planned.route_cells.index((2, 3))
    assert "not optimized" in planned.heuristic_disclosure


def test_missing_target_is_infeasible(scene):
    _, _, provider, request = scene
    target = uuid4()
    planned = routing_service.plan_route(request(return_to_base=False, required_target_ids=[target]), provider)
    assert not planned.feasible and "required_target_unavailable" in planned.constraint_conflicts
    assert planned.distance_m is planned.estimated_duration_min is None


def test_required_target_outside_grid_is_infeasible(scene):
    _, analysis, provider, request = scene
    target_id = uuid4()
    analysis.science_targets = [ScienceTarget(id=target_id, location=LonLat(latitude_deg=80, longitude_deg_east=80),
        title="outside", objective_category="x", relevance_score=.5, confidence="unknown", evidence=[])]
    planned = routing_service.plan_route(request(return_to_base=False, required_target_ids=[target_id]), provider)
    assert not planned.feasible and "required_target_outside_grid" in planned.constraint_conflicts
    assert planned.route_cells == () and planned.distance_m is None


def test_multiple_targets_count_limit_and_elevation_gain(scene):
    routing, analysis, provider, request = scene
    targets = [uuid4(), uuid4()]
    analysis.science_targets = [ScienceTarget(id=tid, location=routing.cell_center_lonlat(row, col), title=str(i),
        objective_category="x", relevance_score=.5, confidence="unknown", evidence=[])
        for i, (tid, row, col) in enumerate(zip(targets, (2, 3), (1, 3)))]
    too_many = routing_service.plan_route(request(return_to_base=False, required_target_ids=targets, max_target_count=1), provider)
    assert not too_many.feasible and "max_target_count_exceeded" in too_many.constraint_conflicts
    elevation = routing.elevation_m.copy(); elevation[2, 1] = 10
    bad = replace(routing, elevation_m=elevation)
    original = routing_service.load_routing_terrain; routing_service.load_routing_terrain = lambda *_: bad
    try:
        planned = routing_service.plan_route(request(return_to_base=False, required_target_ids=[targets[0]],
            max_elevation_gain_m=1), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert not planned.feasible and "max_elevation_gain_exceeded" in planned.constraint_conflicts


def test_output_is_deterministic(scene):
    _, _, provider, request = scene
    req = request(return_to_base=False)
    assert routing_service.plan_route(req, provider) == routing_service.plan_route(req, provider)


def test_astar_heuristic_is_admissible_for_metric_path_cost(scene):
    routing, analysis, _, request = scene
    grid = adapt_routing_terrain(routing, analysis)
    req = request(return_to_base=False)
    adapted = adapt_route_request(req, start=(1, 1), goal=(4, 4), base=(1, 1))
    costs = build_cost_model(grid.terrain_model, adapted.preferences, adapted.limits)
    path = find_path(grid.terrain_model, costs, (1, 1), (4, 4))
    assert path is not None
    lower_bound = _heuristic(grid.terrain_model, (1, 1), (4, 4), costs.minimum_traversable_cost_per_m)
    assert lower_bound <= path.weighted_cost
    assert path.distance_m >= grid.grid.spec.distance_m((1, 1), (4, 4))


def test_astar_prevents_diagonal_corner_cutting(scene):
    routing, _, provider, request = scene
    valid = np.zeros_like(routing.valid); valid[1, 1] = True; valid[2, 2] = True
    elevation = np.full_like(routing.elevation_m, np.nan); elevation[1, 1] = 0; elevation[2, 2] = 0
    bad = replace(routing, valid=valid, elevation_m=elevation)
    original = routing_service.load_routing_terrain; routing_service.load_routing_terrain = lambda *_: bad
    try:
        result = routing_service.plan_route(request(start=(1, 1), destination=(2, 2), return_to_base=False), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert not result.feasible
    assert result.distance_m is None


def test_target_cell_that_is_unknown_is_not_silently_skipped(scene):
    routing, analysis, provider, request = scene
    target_id = uuid4()
    analysis.science_targets = [ScienceTarget(id=target_id, location=routing.cell_center_lonlat(2, 2),
        title="blocked", objective_category="x", relevance_score=.5, confidence="unknown", evidence=[])]
    valid = routing.valid.copy(); valid[2, 2] = False
    elevation = routing.elevation_m.copy(); elevation[2, 2] = np.nan
    bad = replace(routing, valid=valid, elevation_m=elevation)
    original = routing_service.load_routing_terrain; routing_service.load_routing_terrain = lambda *_: bad
    try:
        result = routing_service.plan_route(request(start=(2, 1), destination=(2, 4), return_to_base=False,
            required_target_ids=[target_id]), provider)
    finally:
        routing_service.load_routing_terrain = original
    assert not result.feasible and "unknown_terrain" in result.constraint_conflicts
    assert result.route_cells == () and result.distance_m is None


def test_unsupported_capabilities_are_disclosed(scene):
    _, _, provider, request = scene
    result = routing_service.plan_route(request(return_to_base=False), provider)
    warnings = " ".join(result.warnings).lower()
    assert "science-cost raster" in warnings
    assert "confidence raster" in warnings
    assert "hazard raster" in warnings and "cannot be certified" in warnings
