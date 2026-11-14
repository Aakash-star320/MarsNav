"""Route execution orchestration. No API endpoints or data acquisition live here."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from app.analyzer.integration.routing_terrain import (
    RoutingTerrain, TerrainAccessError, load_routing_terrain,
)
from app.schemas import RegionalAnalysisResult, RouteRequest as ApiRouteRequest

from .analysis_adapter import adapt_routing_terrain
from .costs import CostModel, build_cost_model
from .feasibility import RouteOutcome, plan_mission
from .request_adapter import AdaptedRouteRequest, adapt_route_request, apply_duration_limit
from .terrain import Cell


class AnalysisProvider(Protocol):
    def get_job(self, job_id: UUID): ...
    def get_result(self, job_id: UUID) -> RegionalAnalysisResult | None: ...
    def load_terrain(self, job_id: UUID): ...


@dataclass(frozen=True)
class RoutePlanningResult:
    feasible: bool
    route_cells: tuple[Cell, ...]
    waypoint_cells: tuple[Cell, ...]
    target_ids: tuple[UUID, ...]
    distance_m: float | None
    estimated_duration_min: float | None
    max_slope_deg: float | None
    elevation_gain_m: float | None
    warnings: tuple[str, ...]
    constraint_conflicts: tuple[str, ...]
    analysis_id: UUID
    analysis_version: str
    layer_ids: tuple[str, ...]
    formula_version: str
    heuristic_disclosure: str
    terrain_version: str | None = None
    terrain_sha256: str | None = None


def _failure(request: ApiRouteRequest, conflicts: tuple[str, ...], warnings: tuple[str, ...] = ()) -> RoutePlanningResult:
    return RoutePlanningResult(False, (), (), tuple(request.constraints.required_target_ids), None, None,
        None, None, warnings, conflicts, request.analysis_id, request.analysis_version, (), "",
        "Required targets are visited in request order; target ordering is not optimized.")


def _route_slope_gain(outcome: RouteOutcome, terrain) -> tuple[float | None, float | None]:
    if not outcome.path_cells:
        return None, None
    slopes = [terrain.at(cell).slope_deg for cell in outcome.path_cells]
    known_slopes = [value for value in slopes if value is not None]
    elevations = [terrain.at(cell).elevation_m for cell in outcome.path_cells]
    if any(value is None for value in elevations):
        gain = None
    else:
        gain = sum(max(0.0, float(second) - float(first)) for first, second in zip(elevations, elevations[1:]))
    return (max(known_slopes) if known_slopes else None), gain


def plan_route(request: ApiRouteRequest, analysis_service: AnalysisProvider, blocked_cells: frozenset[Cell] = frozenset()) -> RoutePlanningResult:
    """Load verified analysis, adapt it, and execute deterministic mission routing.

    Required target stops follow ``constraints.required_target_ids`` order. This is
    deterministic and preserves user intent, but does not optimize multi-stop order.
    """
    routing = load_routing_terrain(analysis_service, request.analysis_id, request.analysis_version)
    analysis = analysis_service.get_result(request.analysis_id)
    if analysis is None:
        raise TerrainAccessError("unavailable", "the analysis result artifact is missing")
    if analysis.mission_id != request.mission_id:
        return _failure(request, ("mission_id_mismatch",))

    adapted_grid = adapt_routing_terrain(routing, analysis)
    warnings = list(adapted_grid.warnings)
    start = routing.lonlat_to_cell(request.start)
    goal = routing.lonlat_to_cell(request.destination)
    if start is None:
        return _failure(request, ("start_outside_grid",), tuple(warnings))
    if goal is None:
        return _failure(request, ("destination_outside_grid",), tuple(warnings))

    targets_by_id = {target.id: target for target in analysis.science_targets}
    requested_ids = request.constraints.required_target_ids
    if len(set(requested_ids)) != len(requested_ids):
        return _failure(request, ("duplicate_required_target_id",), tuple(warnings))
    missing = tuple(target_id for target_id in requested_ids if target_id not in targets_by_id)
    if missing:
        return _failure(request, tuple("required_target_unavailable" for _ in missing), tuple(warnings))
    target_cells: list[Cell] = []
    for target_id in requested_ids:
        cell = routing.lonlat_to_cell(targets_by_id[target_id].location)
        if cell is None:
            return _failure(request, ("required_target_outside_grid",), tuple(warnings))
        target_cells.append(cell)

    if len(requested_ids) > (request.constraints.max_target_count or len(requested_ids)):
        return _failure(request, ("max_target_count_exceeded",), tuple(warnings))
    if requested_ids:
        warnings.append("Required targets are visited in request order; multi-target ordering is not optimized.")

    adapted: AdaptedRouteRequest = adapt_route_request(request, start=start, goal=goal,
        base=start, waypoints=tuple(target_cells), target_count=len(requested_ids))
    warnings.extend(adapted.capability_warnings)
    costs: CostModel = build_cost_model(adapted_grid.terrain_model, adapted.preferences, adapted.limits)
    engine_request = replace(adapted.request, blocked_cells=frozenset(blocked_cells)) if blocked_cells else adapted.request
    outcome = plan_mission(adapted_grid.terrain_model, costs, engine_request, adapted.limits)
    outcome = apply_duration_limit(outcome, adapted)
    max_slope, elevation_gain = _route_slope_gain(outcome, adapted_grid.terrain_model)

    conflicts = list(outcome.conflicts)
    max_gain = request.constraints.max_elevation_gain_m
    if max_gain is not None:
        if elevation_gain is None:
            conflicts.append("max_elevation_gain_cannot_be_verified")
        elif elevation_gain > max_gain:
            conflicts.append("max_elevation_gain_exceeded")
    feasible = outcome.status == "ok" and not conflicts
    duration = (outcome.distance_m / adapted.traversal_speed_m_per_min
                + len(requested_ids) * adapted.examination_time_per_target_min
                if feasible and outcome.distance_m is not None else None)
    return RoutePlanningResult(
        feasible=feasible,
        route_cells=outcome.path_cells if feasible else (),
        waypoint_cells=tuple(target_cells) if feasible else (),
        target_ids=tuple(requested_ids),
        distance_m=outcome.distance_m if feasible else None,
        estimated_duration_min=duration if feasible else None,
        max_slope_deg=max_slope if feasible else None,
        elevation_gain_m=elevation_gain if feasible else None,
        warnings=tuple(dict.fromkeys(warnings)),
        constraint_conflicts=tuple(dict.fromkeys(conflicts)),
        analysis_id=routing.analysis_id,
        analysis_version=routing.analysis_version,
        layer_ids=adapted_grid.layer_ids,
        formula_version=outcome.formula_version,
        heuristic_disclosure="Required targets are visited in request order; target ordering is not optimized.",
        terrain_version=routing.terrain_version,
        terrain_sha256=routing.sha256,
    )
