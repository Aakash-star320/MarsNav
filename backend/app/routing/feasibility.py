from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Iterable

from .costs import CostModel, TraversalLimits
from .pathfinding import AStarResult, find_path
from .terrain import Cell, TerrainModel


@dataclass(frozen=True)
class RouteRequest:
    start: Cell
    goal: Cell
    waypoints: tuple[Cell, ...] = ()
    base: Cell | None = None
    return_to_base: bool = False
    available_distance_m: float | None = None
    reserve_distance_m: float = 0.0
    blocked_cells: frozenset[Cell] = frozenset()

    def __post_init__(self) -> None:
        if self.available_distance_m is not None and self.available_distance_m < 0:
            raise ValueError("available_distance_m must be non-negative")
        if self.reserve_distance_m < 0:
            raise ValueError("reserve_distance_m must be non-negative")
        if self.return_to_base and self.base is None:
            raise ValueError("base is required when return_to_base is enabled")


@dataclass(frozen=True)
class RouteOutcome:
    status: str
    path_cells: tuple[Cell, ...]
    distance_m: float | None
    weighted_cost: float | None
    outbound_distance_m: float | None
    return_distance_m: float | None
    reserve_distance_m: float | None
    remaining_distance_m: float | None
    expanded_nodes: int | None
    elevation_profile_m: tuple[float | None, ...]
    conflicts: tuple[str, ...]
    conflict_details: tuple[tuple[str, int], ...]
    formula_version: str
    source_layer_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "path": [{"row": row, "col": col} for row, col in self.path_cells],
            "metrics": {
                "distance_m": None if self.distance_m is None else round(self.distance_m, 3),
                "weighted_cost": None if self.weighted_cost is None else round(self.weighted_cost, 3),
                "outbound_distance_m": None if self.outbound_distance_m is None else round(self.outbound_distance_m, 3),
                "return_distance_m": None if self.return_distance_m is None else round(self.return_distance_m, 3),
                "reserve_distance_m": None if self.reserve_distance_m is None else round(self.reserve_distance_m, 3),
                "remaining_distance_m": None if self.remaining_distance_m is None else round(self.remaining_distance_m, 3),
                "expanded_nodes": self.expanded_nodes,
            },
            "elevation_profile_m": list(self.elevation_profile_m),
            "conflicts": list(self.conflicts),
            "conflict_details": [{"reason": reason, "cells": count} for reason, count in self.conflict_details],
            "formula_version": self.formula_version,
            "source_layer_ids": list(self.source_layer_ids),
        }


def _diagnose_unreachable(costs: CostModel, start: Cell, goal: Cell, blocked_cells: frozenset[Cell]) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
    spec = costs.terrain.grid.spec
    if not spec.contains(start):
        return ("start_outside_grid",), ()
    if not spec.contains(goal):
        return ("goal_outside_grid",), ()
    if start in blocked_cells:
        return ("start_in_blocked_region",), ()
    if goal in blocked_cells:
        return ("goal_in_blocked_region",), ()
    if not costs.at(start).traversable:
        return tuple(costs.at(start).blocked_reasons) or ("start_not_traversable",), ()
    if not costs.at(goal).traversable:
        return tuple(costs.at(goal).blocked_reasons) or ("goal_not_traversable",), ()

    queue = deque([start])
    visited = {start}
    frontier_reasons: Counter[str] = Counter()
    while queue:
        row, col = queue.popleft()
        for dr, dc in ((-1, 0), (0, 1), (1, 0), (0, -1), (-1, 1), (1, 1), (1, -1), (-1, -1)):
            neighbour = (row + dr, col + dc)
            if not spec.contains(neighbour) or neighbour in blocked_cells:
                continue
            if neighbour in visited:
                continue
            if costs.at(neighbour).traversable:
                visited.add(neighbour)
                queue.append(neighbour)
            else:
                reasons = costs.at(neighbour).blocked_reasons or ("not_traversable",)
                for reason in reasons:
                    frontier_reasons[reason] += 1
    if goal in visited:
        return ("diagonal_corner_constraints_or_search_conflict",), ()
    if not frontier_reasons:
        return ("no_connected_traversable_region",), ()
    details = tuple(sorted(frontier_reasons.items(), key=lambda item: (-item[1], item[0])))
    return tuple(reason for reason, _ in details), details


def _join_paths(paths: list[AStarResult]) -> tuple[Cell, ...]:
    joined: list[Cell] = []
    for result in paths:
        if not joined:
            joined.extend(result.cells)
        else:
            joined.extend(result.cells[1:])
    return tuple(joined)


def plan_mission(
    terrain: TerrainModel,
    costs: CostModel,
    request: RouteRequest,
    limits: TraversalLimits | None = None,
) -> RouteOutcome:
    limits = limits or TraversalLimits()
    spec = terrain.grid.spec
    legs: list[tuple[Cell, Cell]] = []
    stops = (request.start,) + request.waypoints + (request.goal,)
    for first, second in zip(stops, stops[1:]):
        legs.append((first, second))

    if request.return_to_base:
        assert request.base is not None
        legs.append((request.goal, request.base))

    found: list[AStarResult] = []
    for first, second in legs:
        result = find_path(terrain, costs, first, second, request.blocked_cells)
        if result is None:
            reasons, details = _diagnose_unreachable(costs, first, second, request.blocked_cells)
            return RouteOutcome(
                status="no_route", path_cells=(), distance_m=None, weighted_cost=None,
                outbound_distance_m=None, return_distance_m=None,
                reserve_distance_m=None, remaining_distance_m=None,
                expanded_nodes=None, elevation_profile_m=(), conflicts=reasons,
                conflict_details=details, formula_version=f"{terrain.formula_version}+{costs.formula_version}",
                source_layer_ids=terrain.source_layer_ids,
            )
        found.append(result)

    path = _join_paths(found)
    outbound_count = len(legs) - (1 if request.return_to_base else 0)
    outbound_distance = sum(result.distance_m for result in found[:outbound_count])
    return_distance = sum(result.distance_m for result in found[outbound_count:])
    route_distance = outbound_distance + return_distance
    weighted_cost = sum(result.weighted_cost for result in found)
    expanded_nodes = sum(result.expanded_nodes for result in found)
    required_distance = route_distance + request.reserve_distance_m
    remaining = None if request.available_distance_m is None else request.available_distance_m - required_distance

    conflicts: list[str] = []
    if limits.max_route_distance_m is not None and route_distance > limits.max_route_distance_m:
        conflicts.append("max_route_distance_exceeded")
    if request.available_distance_m is not None and required_distance > request.available_distance_m:
        conflicts.append("return_base_and_reserve_exceed_available_distance")

    profile = tuple(terrain.at(cell).elevation_m for cell in path)
    feasible = not conflicts
    return RouteOutcome(
        status="ok" if feasible else "infeasible",
        path_cells=path if feasible else (),
        distance_m=route_distance if feasible else None,
        weighted_cost=weighted_cost if feasible else None,
        outbound_distance_m=outbound_distance if feasible else None,
        return_distance_m=return_distance if feasible else None,
        reserve_distance_m=request.reserve_distance_m if feasible else None,
        remaining_distance_m=remaining if feasible else None,
        expanded_nodes=expanded_nodes if feasible else None,
        elevation_profile_m=profile if feasible else (),
        conflicts=tuple(conflicts),
        conflict_details=tuple((reason, 1) for reason in conflicts),
        formula_version=f"{terrain.formula_version}+{costs.formula_version}",
        source_layer_ids=terrain.source_layer_ids,
    )


def replan_around_blocked_region(
    terrain: TerrainModel,
    costs: CostModel,
    request: RouteRequest,
    newly_blocked_cells: Iterable[Cell],
    limits: TraversalLimits | None = None,
) -> RouteOutcome:
    updated = RouteRequest(
        start=request.start,
        goal=request.goal,
        waypoints=request.waypoints,
        base=request.base,
        return_to_base=request.return_to_base,
        available_distance_m=request.available_distance_m,
        reserve_distance_m=request.reserve_distance_m,
        blocked_cells=frozenset(request.blocked_cells).union(newly_blocked_cells),
    )
    return plan_mission(terrain, costs, updated, limits)
