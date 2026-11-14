"""Pure conversion from public route contracts to the internal routing engine."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

from app.schemas import RouteRequest as ApiRouteRequest, RoutePreset

from .costs import CostPreferences, TraversalLimits
from .feasibility import RouteOutcome, RouteRequest as EngineRouteRequest


@dataclass(frozen=True)
class AdaptedRouteRequest:
    preferences: CostPreferences
    limits: TraversalLimits
    request: EngineRouteRequest
    traversal_speed_m_per_min: float
    max_duration_min: float | None
    examination_time_per_target_min: float
    target_count: int
    required_target_ids: tuple[str, ...]
    capability_warnings: tuple[str, ...]


_BUNDLES = {
    RoutePreset.safest: (0.70, 0.20, 0.10),
    RoutePreset.shortest: (0.20, 0.30, 0.50),
    RoutePreset.balanced: (0.40, 0.30, 0.30),
    RoutePreset.science_focused: (0.40, 0.30, 0.30),
}


def adapt_route_request(api: ApiRouteRequest, *, start: tuple[int, int], goal: tuple[int, int],
                        base: tuple[int, int] | None = None, waypoints: tuple[tuple[int, int], ...] = (),
                        target_count: int | None = None) -> AdaptedRouteRequest:
    """Map supported API semantics; report preferences the current model cannot represent."""
    c = api.constraints
    count = len(c.required_target_ids) if target_count is None else target_count
    if count < 0:
        raise ValueError("target_count must be non-negative")
    if c.max_target_count is not None and count > c.max_target_count:
        raise ValueError("target_count exceeds max_target_count")
    if c.return_to_base and base is None:
        base = start

    p = api.preferences
    preset = api.preset or RoutePreset.balanced
    sw, rw, hw = _BUNDLES[preset]
    warnings: list[str] = []
    # Explicit values are treated as overrides of their preset dimension.
    if p.slope != 2:
        sw = p.slope
    if p.roughness != 2:
        rw = p.roughness
    if p.hazard != 3:
        hw = p.hazard
    if p.science > 0:
        warnings.append("science preference is unsupported: no science-cost raster is available")
    if p.confidence > 0:
        warnings.append("confidence preference is unsupported: no confidence raster is available")
    if p.elevation_gain != 1:
        warnings.append("elevation gain preference is unsupported by the cost model")
    if p.distance != 1:
        warnings.append("distance preference is not applied; A* already uses metric distance")
    warnings.append("hazard preference cannot be applied: no hazard raster is available")

    preferences = CostPreferences(slope_weight=sw, roughness_weight=rw, hazard_weight=hw,
                                  unknown_weight=1.0 if c.unknown_terrain_policy.value == "penalize" else 0.0,
                                  unknown_policy="penalize" if c.unknown_terrain_policy.value == "penalize" else "block")
    maximum = c.max_distance_m
    reserve = 0.0 if maximum is None else maximum * c.reserve_fraction
    limits = TraversalLimits(max_slope_deg=c.max_slope_deg,
                             block_unknown=c.unknown_terrain_policy.value == "exclude",
                             max_route_distance_m=maximum)
    engine_request = EngineRouteRequest(start=start, goal=goal, waypoints=waypoints,
        base=base if c.return_to_base else None, return_to_base=c.return_to_base,
        available_distance_m=maximum, reserve_distance_m=reserve)
    return AdaptedRouteRequest(preferences, limits, engine_request, c.traversal_speed_m_per_min,
        c.max_duration_min, c.examination_time_per_target_min, count,
        tuple(str(i) for i in c.required_target_ids), tuple(dict.fromkeys(warnings)))


def apply_duration_limit(outcome: RouteOutcome, adapted: AdaptedRouteRequest) -> RouteOutcome:
    """Apply duration as a post-search feasibility check, including return and target stops."""
    if adapted.max_duration_min is None or outcome.status != "ok":
        return outcome
    duration = outcome.distance_m / adapted.traversal_speed_m_per_min + adapted.target_count * adapted.examination_time_per_target_min
    if not isfinite(duration) or duration > adapted.max_duration_min:
        conflicts = tuple(dict.fromkeys((*outcome.conflicts, "max_duration_exceeded")))
        return replace(outcome, status="infeasible", path_cells=(), distance_m=None, weighted_cost=None,
                       outbound_distance_m=None, return_distance_m=None, reserve_distance_m=None,
                       remaining_distance_m=None, expanded_nodes=None, elevation_profile_m=(), conflicts=conflicts,
                       conflict_details=tuple((*outcome.conflict_details, ("max_duration_exceeded", 1))))
    return outcome
