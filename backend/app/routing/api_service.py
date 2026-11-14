"""Routing as the API sees it: contract-shaped routes, alternatives, replanning around blocked areas and navigation guidance.

The engine in this package plans on grid cells. This module is the layer between it and the public contracts:
* converts engine results to ``RouteResult`` (longitude/latitude geometry, segments, elevation profile, provenance);
* plans the three comparison routes (shortest, safest, balanced) and returns the others as ``alternatives``;
* turns ``BlockedArea`` boxes into blocked cells and replans around them;
* answers ``NavigationGuideRequest`` from the stored route.

Routes are kept in memory (bounded, newest wins): after a restart a route id is unknown and the client must plan again.
Everything stays deterministic: the same request on the same analysis gives the same geometry; only route ids are random.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.analyzer.integration.routing_terrain import RoutingTerrain, TerrainAccessError, load_routing_terrain
from app.schemas import (
    BlockedArea,
    ConstraintConflict,
    ElevationProfilePoint,
    LonLat,
    NavigationGuideRequest,
    NavigationInstruction,
    ReplanRequest,
    RouteAlternative,
    RouteMetrics,
    RoutePreset,
    RouteProvenance,
    RouteRequest,
    RouteResult,
    RouteSegment,
)

from .analysis_adapter import adapt_routing_terrain
from .navigation import NavigationInstruction as CellInstruction, build_navigation_instructions
from .service import AnalysisProvider, RoutePlanningResult, plan_route
from .terrain import Cell

COMPARISON_PRESETS = (RoutePreset.shortest, RoutePreset.safest, RoutePreset.balanced)
PRESET_LABEL = {RoutePreset.shortest: "Shortest", RoutePreset.safest: "Safest terrain", RoutePreset.balanced: "Balanced", RoutePreset.science_focused: "Science focused"}
MAX_STORED = 200
COARSE_NOTE = "The terrain is a coarse global elevation model (463 m cells): routes are broad planning paths, not astronaut-scale paths around rocks or small craters."

CONFLICT_TEXT = {
    "start_outside_grid": "The start is outside the analysed area.",
    "destination_outside_grid": "The destination is outside the analysed area.",
    "goal_outside_grid": "The destination is outside the analysed area.",
    "start_in_blocked_region": "The start lies inside a blocked area.",
    "goal_in_blocked_region": "The destination lies inside a blocked area.",
    "no_connected_traversable_region": "No connected terrain the astronaut may cross links the start and the destination.",
    "max_slope_exceeded": "Every way there crosses ground steeper than the maximum slope.",
    "max_route_distance_exceeded": "The shortest feasible route is longer than the maximum distance.",
    "return_base_and_reserve_exceed_available_distance": "The route plus the return to base and the reserve is longer than the available distance.",
    "max_duration_exceeded": "The route, return and target stops take longer than the maximum duration.",
    "max_elevation_gain_exceeded": "The route climbs more than the maximum elevation gain.",
    "max_elevation_gain_cannot_be_verified": "The elevation gain cannot be verified because part of the route has no elevation data.",
    "mission_id_mismatch": "The analysis belongs to a different mission.",
    "required_target_unavailable": "A required science target is not part of this analysis.",
    "required_target_outside_grid": "A required science target is outside the analysed area.",
    "duplicate_required_target_id": "A required science target was listed twice.",
    "max_target_count_exceeded": "More required targets were listed than the maximum target count.",
    "diagonal_corner_constraints_or_search_conflict": "The only way through needs a diagonal squeeze between blocked cells.",
}
HEURISTIC = "Routes are planned on a coarse grid with prototype cost weights and limits, not NASA EVA thresholds. Required targets are visited in request order."


@dataclass
class StoredRoute:
    request: RouteRequest
    request_version: str
    result: RouteResult
    path: list[LonLat]
    cumulative_m: list[float]
    stops: list[tuple[int, CellInstruction]]     # (path index, instruction) for turns and the destination


def request_version(request: RouteRequest) -> str:
    """Stable fingerprint of a request, so a replan can prove it refers to the route it started from."""
    blob = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return "route-request/" + hashlib.sha256(blob.encode()).hexdigest()[:16]


class RouteNotFound(LookupError):
    pass


class RouteConflict(RuntimeError):
    pass


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def blocked_cells_from_areas(routing: RoutingTerrain, areas: list[BlockedArea]) -> frozenset[Cell]:
    """Cells whose centre lies inside any blocked box (planetocentric degrees, east-positive)."""
    if not areas:
        return frozenset()
    rows, cols = routing.shape
    out: set[Cell] = set()
    for row in range(rows):
        for col in range(cols):
            c = routing.cell_center_lonlat(row, col)
            for a in areas:
                b = a.bounds
                if b.west_deg_east <= c.longitude_deg_east <= b.east_deg_east and b.south_deg <= c.latitude_deg <= b.north_deg:
                    out.add((row, col))
                    break
    return frozenset(out)


class RoutingApi:
    def __init__(self, analyses: AnalysisProvider) -> None:
        self._analyses = analyses
        self._lock = threading.Lock()
        self._routes: OrderedDict[UUID, StoredRoute] = OrderedDict()

    # -- public ---------------------------------------------------------------------------------
    def plan(self, request: RouteRequest) -> RouteResult:
        main_preset = request.preset or RoutePreset.balanced
        routing = load_routing_terrain(self._analyses, request.analysis_id, request.analysis_version)
        blocked = blocked_cells_from_areas(routing, request.blocked_areas)
        main = self._plan_one(request.model_copy(update={"preset": main_preset}), routing, blocked)
        alternatives: list[RouteAlternative] = []
        if main.result.feasible:
            seen = [main.path]
            same: list[str] = []
            for preset in COMPARISON_PRESETS:
                if preset == main_preset:
                    continue
                alt = self._plan_one(request.model_copy(update={"preset": preset}), routing, blocked)
                if not (alt.result.feasible and alt.result.metrics is not None):
                    continue
                if alt.path in seen:                          # the same cells: not a different route, so not shown as one
                    same.append(PRESET_LABEL[preset])
                    continue
                seen.append(alt.path)
                self._remember(alt, request)                      # an alternative can be followed and replanned like the main route
                alternatives.append(RouteAlternative(id=alt.result.id, label=PRESET_LABEL[preset], geometry=alt.path, metrics=alt.result.metrics,
                                                     elevation_profile=alt.result.elevation_profile, warnings=alt.result.warnings))
            if same:
                main.result.warnings.append(f"On this terrain the {' and '.join(same)} setting{'s' if len(same) > 1 else ''} give the same route, so no separate alternative is shown.")
        main.result.alternatives = alternatives
        self._remember(main, request)
        return main.result

    def replan(self, req: ReplanRequest) -> RouteResult:
        stored = self._get(req.original_route_id)
        if stored.request.analysis_id != req.analysis_id:
            raise RouteConflict("the replan refers to a different analysis than the original route")
        if stored.request_version != req.original_request_version:
            raise RouteConflict("original_request_version does not match the stored route; plan again")
        updated = stored.request.model_copy(update={"blocked_areas": [*stored.request.blocked_areas, *req.blocked_areas]})
        return self.plan(updated)

    def get(self, route_id: UUID) -> RouteResult:
        return self._get(route_id).result

    def guide(self, req: NavigationGuideRequest) -> NavigationInstruction:
        route = self._get(req.route_id)
        if not route.result.feasible or not route.path:
            raise RouteConflict("that route is not feasible, so there is nothing to follow")
        here, st = req.state.position, req.state
        # nearest vertex on the route (equirectangular distance is plenty at route scale)
        def metres(p: LonLat, q: LonLat) -> float:
            k = math.cos(math.radians((p.latitude_deg + q.latitude_deg) / 2))
            return 3_396_190.0 * math.hypot(math.radians(q.latitude_deg - p.latitude_deg), math.radians(q.longitude_deg_east - p.longitude_deg_east) * k)
        near = min(range(len(route.path)), key=lambda i: metres(here, route.path[i]))
        total = route.cumulative_m[-1]
        remaining = max(0.0, total - route.cumulative_m[near])
        nxt = next(((i, ins) for i, ins in route.stops if i > near), None)
        if nxt is None or near >= len(route.path) - 1:
            return NavigationInstruction(message="You have reached the destination.", relative_turn_deg=None, distance_to_waypoint_m=0.0, remaining_distance_m=0.0)
        idx, ins = nxt
        target = st.next_waypoint or route.path[idx]
        to_wp = metres(here, target)
        k = math.cos(math.radians(here.latitude_deg))
        bearing = (math.degrees(math.atan2(math.radians(target.longitude_deg_east - here.longitude_deg_east) * k, math.radians(target.latitude_deg - here.latitude_deg))) + 360) % 360
        turn = (bearing - st.heading_deg_clockwise_from_north + 540) % 360 - 180
        compass = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")[int((bearing + 22.5) // 45) % 8]
        if abs(turn) <= 15:
            lead = f"Continue {compass} for {to_wp:.0f} m."
        else:
            lead = f"Turn {'right' if turn > 0 else 'left'} {abs(turn):.0f} degrees to head {compass}, then continue {to_wp:.0f} m."
        later = "" if ins.turn == "arrived" else f" Then: {ins.text}."
        return NavigationInstruction(message=lead + later, relative_turn_deg=max(-180.0, min(turn, 179.999)), distance_to_waypoint_m=to_wp, remaining_distance_m=remaining)

    # -- internals --------------------------------------------------------------------------------
    def _get(self, route_id: UUID) -> StoredRoute:
        with self._lock:
            if route_id not in self._routes:
                raise RouteNotFound(f"route {route_id} is unknown (routes are kept in memory; plan again)")
            self._routes.move_to_end(route_id)
            return self._routes[route_id]

    def _remember(self, stored: StoredRoute, request: RouteRequest) -> None:
        with self._lock:
            self._routes[stored.result.id] = stored
            while len(self._routes) > MAX_STORED:
                self._routes.popitem(last=False)

    def _plan_one(self, request: RouteRequest, routing: RoutingTerrain, blocked: frozenset[Cell]) -> StoredRoute:
        planned = plan_route(request, self._analyses, blocked)
        version = request_version(request)
        return self._to_stored(request, version, planned, routing)

    def _to_stored(self, request: RouteRequest, version: str, planned: RoutePlanningResult, routing: RoutingTerrain) -> StoredRoute:
        conflicts = list(planned.constraint_conflicts)
        details = [ConstraintConflict(code=c, message=CONFLICT_TEXT.get(c, c.replace("_", " ").capitalize() + ".")) for c in conflicts]
        provenance = RouteProvenance(
            analysis_version=planned.analysis_version, formula_version=planned.formula_version or "unavailable",
            layer_ids=[UUID(i) for i in planned.layer_ids if _is_uuid(i)], heuristic_disclosure=HEURISTIC,
        )
        base = dict(id=uuid4(), analysis_id=planned.analysis_id, analysis_version=planned.analysis_version, request_version=version,
                    warnings=[*planned.warnings, COARSE_NOTE], constraint_conflicts=conflicts, conflict_details=details, provenance=provenance,
                    target_ids=list(planned.target_ids))
        if not planned.feasible or not planned.route_cells:
            return StoredRoute(request, version, RouteResult(feasible=False, **base), [], [], [])

        cells = list(planned.route_cells)
        path = [routing.cell_center_lonlat(r, c) for r, c in cells]
        xy = [routing.cell_center_xy(r, c) for r, c in cells]
        planar = [0.0]
        for a, b in zip(xy, xy[1:]):
            planar.append(planar[-1] + _dist(a, b))
        scale = (planned.distance_m / planar[-1]) if planar[-1] > 0 and planned.distance_m else 1.0
        cumulative = [d * scale for d in planar]            # sums to the engine's reported distance
        speed = request.constraints.traversal_speed_m_per_min
        profile = [ElevationProfilePoint(distance_m=cumulative[i], elevation_m=_elev(routing, cells[i]), valid=_elev(routing, cells[i]) is not None) for i in range(len(cells))]

        # segments: between the start, each required target, the destination and (if planned) the return to the base
        marks = _stop_indices(cells, list(planned.waypoint_cells), routing, request)
        segments: list[RouteSegment] = []
        for (i0, t0), (i1, _t1) in zip(marks, marks[1:]):
            d = cumulative[i1] - cumulative[i0]
            segments.append(RouteSegment(from_location=path[i0], to_location=path[i1], target_id=_t1, distance_m=d,
                                         estimated_duration_min=d / speed + (request.constraints.examination_time_per_target_min if _t1 else 0.0)))
        metrics = RouteMetrics(distance_m=planned.distance_m or cumulative[-1], estimated_duration_min=planned.estimated_duration_min or 0.0,
                               max_slope_deg=planned.max_slope_deg, elevation_gain_m=planned.elevation_gain_m, science_value=None, confidence="low")
        instr = build_navigation_instructions(adapt_routing_terrain(routing, self._analyses.get_result(request.analysis_id)).terrain_model.grid.spec, cells)
        stops = _instruction_indices(cells, instr)
        result = RouteResult(feasible=True, geometry=path, waypoints=[routing.cell_center_lonlat(r, c) for r, c in planned.waypoint_cells],
                             metrics=metrics, segments=segments, elevation_profile=profile, **base)
        return StoredRoute(request, version, result, path, cumulative, stops)


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def _elev(routing: RoutingTerrain, cell: Cell) -> float | None:
    r, c = cell
    if not bool(routing.valid[r, c]):
        return None
    v = float(routing.elevation_m[r, c])
    return v if math.isfinite(v) else None


def _stop_indices(cells: list[Cell], waypoint_cells: list[Cell], routing: RoutingTerrain, request: RouteRequest) -> list[tuple[int, UUID | None]]:
    """(path index, target id) of the start, every required target, the destination and the end of any return leg."""
    marks: list[tuple[int, UUID | None]] = [(0, None)]
    cursor = 0
    ids = list(request.constraints.required_target_ids)
    for k, w in enumerate(waypoint_cells):
        try:
            cursor = cells.index(w, cursor)
        except ValueError:
            continue
        marks.append((cursor, ids[k] if k < len(ids) else None))
    goal = routing.lonlat_to_cell(request.destination)
    if goal is not None and goal in cells[cursor:]:
        cursor = cells.index(goal, cursor)
        if cursor > marks[-1][0]:
            marks.append((cursor, None))
    if marks[-1][0] != len(cells) - 1:
        marks.append((len(cells) - 1, None))                     # the return leg to the base
    return marks


def _instruction_indices(cells: list[Cell], instructions: tuple[CellInstruction, ...]) -> list[tuple[int, CellInstruction]]:
    out: list[tuple[int, CellInstruction]] = []
    cursor = 0
    for ins in instructions:
        if ins.turn == "start":
            continue
        try:
            cursor = cells.index(ins.cell, cursor)
        except ValueError:
            continue
        out.append((cursor, ins))
    return out
