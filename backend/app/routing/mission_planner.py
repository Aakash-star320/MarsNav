"""Mission planner: pick science targets that fit the time budget, visit them, and get back to base.

Deterministic greedy selection on top of the routing engine (no cost logic is duplicated here):
from the current position, among the targets still left choose the one with the best
``relevance_score / (travel time + examination time)`` that still leaves enough time to reach it, examine it,
get back to the base and keep the reserve; repeat until nothing fits or the stop limit is reached; then go home.
Ties are broken by target id. Targets come only from the analysis result: a target that is not in the analysis is
never planned, and an analysis without targets gives an honest "no targets" answer (which is not evidence that
no hydrated minerals exist).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.analyzer.integration.routing_terrain import RoutingTerrain, load_routing_terrain
from app.schemas import ConstraintConflict, ElevationProfilePoint, LonLat, RouteMetrics, RouteProvenance, RouteRequest, ScienceTarget
from app.schemas.mission_plan import ExcludedTarget, MissionLeg, MissionPlanRequest, MissionPlanResult, MissionStop, MissionTotals

from .analysis_adapter import adapt_routing_terrain
from .api_service import CONFLICT_TEXT, COARSE_NOTE, _elev, _is_uuid, blocked_cells_from_areas
from .costs import CostModel, build_cost_model
from .pathfinding import AStarResult, find_path
from .request_adapter import adapt_route_request
from .service import AnalysisProvider
from .terrain import Cell

FORMULA = "mission-greedy/1"
HEURISTIC = ("Targets are chosen greedily by relevance score per minute of travel and examination, then visited in that order; this is a "
             "planning heuristic, not an optimal tour. Relevance scores are heuristic screens of spectral summary parameters, not identified minerals. "
             "Limits and cost weights are prototype assumptions, not NASA EVA thresholds.")

MISSION_CONFLICT_TEXT = {
    **CONFLICT_TEXT,
    "no_science_targets": "This analysis has no science targets to visit. That is not evidence that none exist: the screen only covers where spectral data was available.",
    "no_target_fits_budget": "No science target can be reached, examined and returned from within the time budget, reserve and limits.",
    "base_outside_grid": "The base is outside the analysed area.",
    "base_in_blocked_region": "The base lies inside a blocked area.",
    "no_route_home": "There is no route back to the base from the last stop.",
}
EXCLUDED_TEXT = {
    "unknown_target": "This target is not part of the analysis.",
    "outside_grid": "The target is outside the analysed area.",
    "blocked": "The target lies inside a blocked area.",
    "leg_slope_exceeds_limit": "The target sits on ground steeper than the maximum slope.",
    "unknown_terrain": "The target sits on terrain with no usable data, which the limits exclude.",
    "no_route": "No route the astronaut may take leads to the target or back from it.",
    "does_not_fit_time_budget": "It does not fit the time budget: travel, examination, the way back to base and the reserve take too long.",
    "exceeds_maximum_distance": "It does not fit the maximum distance once the way back to base and the reserve are counted.",
    "max_target_count_reached": "The limit on the number of stops was reached before this target.",
}


@dataclass(frozen=True)
class _Candidate:
    target: ScienceTarget
    cell: Cell
    back: AStarResult | None          # the way from the target to the base (does not depend on where we are)


def _leg(routing: RoutingTerrain, terrain, path: AStarResult, speed: float, science: float | None) -> MissionLeg:
    """Contract leg: lon/lat geometry, metrics and an elevation profile whose distances sum to the engine's distance."""
    cells = list(path.cells)
    xy = [routing.cell_center_xy(r, c) for r, c in cells]
    planar = [0.0]
    for a, b in zip(xy, xy[1:]):
        planar.append(planar[-1] + math.hypot(a[0] - b[0], a[1] - b[1]))
    scale = (path.distance_m / planar[-1]) if planar[-1] > 0 else 1.0
    dist = [d * scale for d in planar]
    elevs = [_elev(routing, c) for c in cells]
    slopes = [terrain.at(c).slope_deg for c in cells]
    known = [s for s in slopes if s is not None]
    gain = None if any(e is None for e in elevs) else sum(max(0.0, float(b) - float(a)) for a, b in zip(elevs, elevs[1:]))
    return MissionLeg(
        geometry=[routing.cell_center_lonlat(r, c) for r, c in cells],
        metrics=RouteMetrics(distance_m=path.distance_m, estimated_duration_min=path.distance_m / speed, max_slope_deg=max(known) if known else None,
                             elevation_gain_m=gain, science_value=science, confidence="low"),
        elevation_profile=[ElevationProfilePoint(distance_m=dist[i], elevation_m=elevs[i], valid=elevs[i] is not None) for i in range(len(cells))],
    )


def _cell_problem(costs: CostModel, cell: Cell) -> str | None:
    reasons = costs.at(cell).blocked_reasons if not costs.at(cell).traversable else ()
    if "max_slope_exceeded" in reasons:
        return "leg_slope_exceeds_limit"
    if reasons:
        return "unknown_terrain" if any("unknown" in r or r == "outside_valid_mask" for r in reasons) else "no_route"
    return None


def plan_mission_trip(request: MissionPlanRequest, analyses: AnalysisProvider, request_version: str) -> MissionPlanResult:
    routing = load_routing_terrain(analyses, request.analysis_id, request.analysis_version)
    analysis = analyses.get_result(request.analysis_id)
    c = request.constraints
    budget = c.max_duration_min
    reserve_min = (budget * c.reserve_fraction) if budget is not None else 0.0
    speed, exam = c.traversal_speed_m_per_min, c.examination_time_per_target_min
    warnings: list[str] = [COARSE_NOTE]
    base_kwargs = dict(id=uuid4(), analysis_id=request.analysis_id, analysis_version=routing.analysis_version, request_version=request_version)

    def provenance(formula: str = "unavailable", layers: tuple[str, ...] = ()) -> RouteProvenance:
        return RouteProvenance(analysis_version=routing.analysis_version, formula_version=formula, layer_ids=[UUID(i) for i in layers if _is_uuid(i)], heuristic_disclosure=HEURISTIC)

    def failure(codes: list[str], excluded: list[ExcludedTarget] | None = None, formula: str = "unavailable", layers: tuple[str, ...] = ()) -> MissionPlanResult:
        return MissionPlanResult(
            feasible=False, totals=MissionTotals(distance_m=0, duration_min=0, reserve_min=reserve_min, budget_min=budget, remaining_min=None, science_value=None),
            excluded=excluded or [], warnings=list(dict.fromkeys(warnings)), constraint_conflicts=codes,
            conflict_details=[ConstraintConflict(code=k, message=MISSION_CONFLICT_TEXT.get(k, k.replace("_", " ").capitalize() + ".")) for k in codes],
            provenance=provenance(formula, layers), **base_kwargs)

    if analysis is None:
        raise ValueError("the analysis result artifact is missing")
    if analysis.mission_id != request.mission_id:
        return failure(["mission_id_mismatch"])

    adapted_grid = adapt_routing_terrain(routing, analysis)
    warnings += list(adapted_grid.warnings)
    terrain = adapted_grid.terrain_model
    start, base = routing.lonlat_to_cell(request.start), routing.lonlat_to_cell(request.base)
    layers = adapted_grid.layer_ids
    if start is None or base is None:
        return failure(["start_outside_grid" if start is None else "base_outside_grid"], layers=layers)

    # The engine's own request adapter turns the contract limits and weights into cost preferences and traversal limits.
    api = RouteRequest(mission_id=request.mission_id, analysis_id=request.analysis_id, analysis_version=request.analysis_version, start=request.start,
                       destination=request.base, preferences=request.preferences, constraints=c.model_copy(update={"required_target_ids": []}))
    adapted = adapt_route_request(api, start=start, goal=base, base=base, waypoints=(), target_count=0)
    warnings += list(adapted.capability_warnings)
    costs = build_cost_model(terrain, adapted.preferences, adapted.limits)
    formula = f"{FORMULA}+{terrain.formula_version}+{costs.formula_version}"
    blocked = blocked_cells_from_areas(routing, request.blocked_areas)
    if start in blocked or base in blocked:
        return failure(["start_in_blocked_region" if start in blocked else "base_in_blocked_region"], formula=formula, layers=layers)

    # -- candidates: only targets of this analysis ------------------------------------------------------------
    by_id = {t.id: t for t in analysis.science_targets}
    wanted = list(dict.fromkeys(request.target_ids)) if request.target_ids is not None else sorted(by_id, key=str)
    excluded: dict[UUID, ExcludedTarget] = {}

    def exclude(tid: UUID, code: str) -> None:
        excluded[tid] = ExcludedTarget(target_id=tid, code=code, message=EXCLUDED_TEXT[code])

    for tid in wanted:
        if tid not in by_id:
            exclude(tid, "unknown_target")
    pool = [by_id[t] for t in wanted if t in by_id]
    if not by_id:
        return failure(["no_science_targets"], formula=formula, layers=layers)
    candidates: dict[UUID, _Candidate] = {}
    for t in pool:
        cell = routing.lonlat_to_cell(t.location)
        if cell is None:
            exclude(t.id, "outside_grid")
        elif cell in blocked:
            exclude(t.id, "blocked")
        elif (problem := _cell_problem(costs, cell)) is not None:
            exclude(t.id, problem)
        else:
            back = find_path(terrain, costs, cell, base, blocked)
            if back is None:
                exclude(t.id, "no_route")
            else:
                candidates[t.id] = _Candidate(t, cell, back)

    # -- greedy tour -----------------------------------------------------------------------------------------------
    usable = None if budget is None else budget - reserve_min
    max_dist = c.max_distance_m
    dist_cap = None if max_dist is None else max_dist * (1 - c.reserve_fraction)
    stops: list[MissionStop] = []
    position, elapsed, travelled = start, 0.0, 0.0
    last_reason: dict[UUID, str] = {}
    remaining = dict(candidates)
    while remaining and (c.max_target_count is None or len(stops) < c.max_target_count):
        best: tuple[float, str, _Candidate, AStarResult] | None = None
        for tid in sorted(remaining, key=str):
            cand = remaining[tid]
            leg = find_path(terrain, costs, position, cand.cell, blocked)
            if leg is None:
                exclude(tid, "no_route")
                del remaining[tid]
                continue
            assert cand.back is not None
            leg_t, back_t = leg.distance_m / speed, cand.back.distance_m / speed
            if usable is not None and elapsed + leg_t + exam + back_t > usable + 1e-9:
                last_reason[tid] = "does_not_fit_time_budget"
                continue
            if dist_cap is not None and travelled + leg.distance_m + cand.back.distance_m > dist_cap + 1e-9:
                last_reason[tid] = "exceeds_maximum_distance"
                continue
            score = round(cand.target.relevance_score / max(leg_t + exam, 1e-9), 12)
            if best is None or (-score, str(tid)) < (-best[0], best[1]):
                best = (score, str(tid), cand, leg)
        if best is None:
            break
        _, _, cand, leg = best
        arrival = elapsed + leg.distance_m / speed
        stops.append(MissionStop(order=len(stops) + 1, target_id=cand.target.id, arrival_min=arrival, examination_min=exam,
                                 leg=_leg(routing, terrain, leg, speed, cand.target.relevance_score)))
        elapsed, travelled, position = arrival + exam, travelled + leg.distance_m, cand.cell
        del remaining[cand.target.id]
        last_reason.pop(cand.target.id, None)
    for tid in remaining:
        if c.max_target_count is not None and len(stops) >= c.max_target_count and tid not in last_reason:
            exclude(tid, "max_target_count_reached")
        else:
            exclude(tid, last_reason.get(tid, "does_not_fit_time_budget"))
    excluded_list = sorted(excluded.values(), key=lambda e: str(e.target_id))

    if not stops:
        return failure(["no_target_fits_budget"], excluded_list, formula, layers)
    home = find_path(terrain, costs, position, base, blocked)
    if home is None:
        return failure(["no_route_home"], excluded_list, formula, layers)
    return_leg = _leg(routing, terrain, home, speed, None)
    travelled += home.distance_m
    duration = travelled / speed + exam * len(stops)
    value = sum(by_id[s.target_id].relevance_score for s in stops)
    if budget is None:
        warnings.append("No duration limit was set, so the time budget did not constrain the plan.")
    warnings.append("Targets are visited in the order the planner chose; the order is not optimal.")
    return MissionPlanResult(
        feasible=True, stops=stops, return_leg=return_leg,
        totals=MissionTotals(distance_m=travelled, duration_min=duration, reserve_min=reserve_min, budget_min=budget,
                             remaining_min=None if budget is None else budget - reserve_min - duration, science_value=value),
        excluded=excluded_list, warnings=list(dict.fromkeys(warnings)), constraint_conflicts=[], conflict_details=[],
        provenance=provenance(formula, layers), **base_kwargs)
