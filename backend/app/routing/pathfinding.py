from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from math import hypot
from typing import Iterable

from .costs import CostModel
from .terrain import Cell, TerrainModel

# Fixed order plus row/column heap tie-breaking makes routes reproducible.
_NEIGHBOURS: tuple[Cell, ...] = (
    (-1, 0), (0, 1), (1, 0), (0, -1),
    (-1, 1), (1, 1), (1, -1), (-1, -1),
)


@dataclass(frozen=True)
class AStarResult:
    cells: tuple[Cell, ...]
    distance_m: float
    weighted_cost: float
    expanded_nodes: int


def _heuristic(terrain: TerrainModel, first: Cell, goal: Cell, minimum_cost_per_m: float) -> float:
    return terrain.grid.spec.distance_m(first, goal) * minimum_cost_per_m


def _diagonal_is_clear(costs: CostModel, current: Cell, neighbour: Cell, blocked_cells: frozenset[Cell]) -> bool:
    dr = neighbour[0] - current[0]
    dc = neighbour[1] - current[1]
    if abs(dr) != 1 or abs(dc) != 1:
        return True
    side_a = (current[0] + dr, current[1])
    side_b = (current[0], current[1] + dc)
    spec = costs.terrain.grid.spec
    return (
        spec.contains(side_a)
        and spec.contains(side_b)
        and side_a not in blocked_cells
        and side_b not in blocked_cells
        and costs.at(side_a).traversable
        and costs.at(side_b).traversable
    )


def find_path(
    terrain: TerrainModel,
    costs: CostModel,
    start: Cell,
    goal: Cell,
    blocked_cells: Iterable[Cell] = (),
) -> AStarResult | None:
    """Deterministic A* with metric distances, positive costs and no corner cutting."""
    spec = terrain.grid.spec
    if costs.terrain is not terrain:
        raise ValueError("CostModel must be built from the same TerrainModel")
    if not spec.contains(start) or not spec.contains(goal):
        return None
    additional_blocks = frozenset(blocked_cells)
    if start in additional_blocks or goal in additional_blocks:
        return None
    if not costs.at(start).traversable or not costs.at(goal).traversable:
        return None
    if start == goal:
        return AStarResult(cells=(start,), distance_m=0.0, weighted_cost=0.0, expanded_nodes=0)

    minimum_cost = max(1.0, costs.minimum_traversable_cost_per_m)
    open_heap: list[tuple[float, float, int, int]] = []
    heappush(open_heap, (_heuristic(terrain, start, goal, minimum_cost), 0.0, start[0], start[1]))
    came_from: dict[Cell, Cell] = {}
    g_score: dict[Cell, float] = {start: 0.0}
    distance_score: dict[Cell, float] = {start: 0.0}
    expanded = 0

    while open_heap:
        _, current_g, row, col = heappop(open_heap)
        current = (row, col)
        if current_g > g_score.get(current, float("inf")) + 1e-12:
            continue
        if current == goal:
            path = [goal]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            path.reverse()
            return AStarResult(
                cells=tuple(path),
                distance_m=distance_score[goal],
                weighted_cost=g_score[goal],
                expanded_nodes=expanded,
            )

        expanded += 1
        for dr, dc in _NEIGHBOURS:
            neighbour = (row + dr, col + dc)
            if not spec.contains(neighbour) or neighbour in additional_blocks:
                continue
            neighbour_cost = costs.at(neighbour)
            if not neighbour_cost.traversable or not _diagonal_is_clear(costs, current, neighbour, additional_blocks):
                continue
            step_distance = spec.distance_m(current, neighbour)
            step_cost = step_distance * (costs.at(current).cost_per_m + neighbour_cost.cost_per_m) / 2.0
            tentative = current_g + step_cost
            if tentative + 1e-12 >= g_score.get(neighbour, float("inf")):
                continue
            came_from[neighbour] = current
            g_score[neighbour] = tentative
            distance_score[neighbour] = distance_score[current] + step_distance
            estimate = tentative + _heuristic(terrain, neighbour, goal, minimum_cost)
            heappush(open_heap, (estimate, tentative, neighbour[0], neighbour[1]))

    return None
