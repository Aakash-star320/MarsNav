"""Region planner: the metric analysis area needed for analyze, route and mission modes.

All distance bounds are simulation assumptions (not NASA constants) and are returned in
``assumptions`` so callers can show them. A planned region only says what data to retrieve; actual
reachability is decided by routing.
"""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import BoundingBox, LonLat

from .mars_geometry import (
    GeometryError,
    bounds_area_m2,
    bounds_from_local_extents,
    haversine_m,
    intersect_bounds,
    to_local_xy_m,
)

MIN_BUFFER_M = 1_000.0
BUFFER_FRACTION = 0.5
EXPANSION_FACTOR = 1.5
MAX_ATTEMPTS = 3
MAX_LAT_DEG = 89.0


class RegionPlanningError(ValueError):
    """Structured planning failure; ``code`` distinguishes impossible budget, limits, etc."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EllipseMask(BaseModel):
    focus_a: LonLat
    focus_b: LonLat
    travel_budget_m: float = Field(gt=0)


class RegionPlan(BaseModel):
    mode: Literal["analyze", "route", "mission"]
    bounds: BoundingBox
    travel_bounds: BoundingBox | None = None
    buffer_m: float | None = None
    search_mask: EllipseMask | None = None
    attempt: int = 1
    rationale: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def plan_analyze_region(bounds: BoundingBox, max_area_km2: float | None = None) -> RegionPlan:
    if max_area_km2 is not None and bounds_area_m2(bounds) / 1e6 > max_area_km2:
        raise RegionPlanningError("area_limit", f"region exceeds the {max_area_km2:g} km2 analysis limit; choose a smaller region")
    return RegionPlan(mode="analyze", bounds=bounds, rationale=["User-selected region used as given."])


def _ellipse_rect(a_xy: tuple[float, float], b_xy: tuple[float, float], budget_m: float) -> tuple[float, float, float, float]:
    """(min_x, max_x, min_y, max_y) of the rectangle bounding {P: |AP|+|PB| <= budget}."""
    dx, dy = b_xy[0] - a_xy[0], b_xy[1] - a_xy[1]
    a, c = budget_m / 2.0, math.hypot(dx, dy) / 2.0
    b = math.sqrt(max(a * a - c * c, 0.0))
    theta = math.atan2(dy, dx)
    half_x = math.sqrt((a * math.cos(theta)) ** 2 + (b * math.sin(theta)) ** 2)
    half_y = math.sqrt((a * math.sin(theta)) ** 2 + (b * math.cos(theta)) ** 2)
    cx, cy = (a_xy[0] + b_xy[0]) / 2, (a_xy[1] + b_xy[1]) / 2
    return cx - half_x, cx + half_x, cy - half_y, cy + half_y


def plan_route_region(points: list[LonLat], max_travel_distance_m: float | None = None) -> RegionPlan:
    """Plan the area for a route visiting ``points`` in order (include base last if returning)."""
    if len(points) < 2:
        raise RegionPlanningError("invalid_points", "a route needs at least a start and a destination")
    origin = points[0]
    try:
        xy = [to_local_xy_m(origin, p) for p in points]
        legs = [haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)]
        buffer_m = max(MIN_BUFFER_M, BUFFER_FRACTION * legs[0])
        rect = [min(x for x, _ in xy) - buffer_m, max(x for x, _ in xy) + buffer_m,
                min(y for _, y in xy) - buffer_m, max(y for _, y in xy) + buffer_m]
        rationale = [f"Bounding rectangle of all required points plus buffer max(1 km, 0.5 x straight-line) = {buffer_m:.0f} m."]
        mask = None
        if max_travel_distance_m is not None:
            lower_bound = sum(legs)
            if max_travel_distance_m < lower_bound:
                raise RegionPlanningError(
                    "impossible_budget",
                    f"distance budget {max_travel_distance_m:.0f} m is below the {lower_bound:.0f} m straight-line lower bound",
                )
            rects = [_ellipse_rect(xy[i], xy[i + 1], max_travel_distance_m - (lower_bound - leg)) for i, leg in enumerate(legs)]
            tight = [min(r[0] for r in rects), max(r[1] for r in rects), min(r[2] for r in rects), max(r[3] for r in rects)]
            rect = [max(rect[0], tight[0]), min(rect[1], tight[1]), max(rect[2], tight[2]), min(rect[3], tight[3])]
            rationale.append("Tightened by budget ellipse d(A,P)+d(P,B) <= L, with other mandatory legs subtracted from L.")
            if len(points) == 2:
                mask = EllipseMask(focus_a=points[0], focus_b=points[1], travel_budget_m=max_travel_distance_m)
        bounds = bounds_from_local_extents(origin, *rect)
    except GeometryError as exc:
        raise RegionPlanningError(exc.code, str(exc)) from exc
    return RegionPlan(
        mode="route", bounds=bounds, buffer_m=buffer_m, search_mask=mask, rationale=rationale,
        assumptions=["Local equirectangular frame on a spherical Mars (mean radius 3389.5 km); not a certified safety bound."],
    )


def plan_mission_region(
    start: LonLat, *, duration_min: float, reserve_min: float, min_examination_min: float,
    upper_speed_m_per_min: float, return_to_base: bool = True, return_base: LonLat | None = None,
    max_distance_m: float | None = None, selection_bounds: BoundingBox | None = None,
) -> RegionPlan:
    """Optimistic reachable region for a scientific mission (speed is an upper bound)."""
    travel_min = duration_min - reserve_min - min_examination_min
    if travel_min <= 0:
        raise RegionPlanningError("insufficient_time", "duration minus reserve and minimum examination time leaves no travel time")
    distance_m = upper_speed_m_per_min * travel_min
    if max_distance_m is not None:
        distance_m = min(distance_m, max_distance_m)
    rationale = [f"Travel time {travel_min:g} min x upper-bound speed {upper_speed_m_per_min:g} m/min = {distance_m:.0f} m total travel."]
    mask = None
    try:
        if return_base is not None and return_to_base:
            direct = haversine_m(start, return_base)
            if distance_m < direct:
                raise RegionPlanningError("impossible_budget", f"travel bound {distance_m:.0f} m is below the {direct:.0f} m start-to-base distance")
            extents = _ellipse_rect((0.0, 0.0), to_local_xy_m(start, return_base), distance_m)
            mask = EllipseMask(focus_a=start, focus_b=return_base, travel_budget_m=distance_m)
            rationale.append("Different return base: ellipse with foci at start and base.")
        else:
            radius = distance_m / 2.0 if return_to_base else distance_m
            extents = (-radius, radius, -radius, radius)
            rationale.append(f"Search radius {radius:.0f} m ({'out-and-back, half the travel distance' if return_to_base else 'one-way'}).")
        travel_bounds = bounds_from_local_extents(start, *extents)
    except GeometryError as exc:
        raise RegionPlanningError(exc.code, str(exc)) from exc
    bounds = travel_bounds
    if selection_bounds is not None:
        inter = intersect_bounds(travel_bounds, selection_bounds)
        if inter is None:
            raise RegionPlanningError("no_overlap", "selected science area does not overlap the reachable search area")
        bounds = inter
        rationale.append("Target-selection area intersected with the optimistic travel boundary.")
    return RegionPlan(
        mode="mission", bounds=bounds, travel_bounds=travel_bounds, search_mask=mask, rationale=rationale,
        assumptions=["Speed is a simulation upper bound, not NASA-certified.", "Circle/ellipse membership is optimistic; routing decides real reachability."],
    )


def expand_region(plan: RegionPlan, hard_bounds: BoundingBox | None = None, factor: float = EXPANSION_FACTOR) -> RegionPlan:
    """Grow a plan after a boundary-limited routing failure (max three attempts in total)."""
    if plan.attempt >= MAX_ATTEMPTS:
        raise RegionPlanningError("expansion_limit", f"already used {plan.attempt} of {MAX_ATTEMPTS} attempts")
    b = plan.bounds
    cx, cy = (b.west_deg_east + b.east_deg_east) / 2, (b.south_deg + b.north_deg) / 2
    hw, hh = (b.east_deg_east - b.west_deg_east) / 2 * factor, (b.north_deg - b.south_deg) / 2 * factor
    west, east = max(cx - hw, -180.0), min(cx + hw, 179.999999)
    south, north = max(cy - hh, -MAX_LAT_DEG), min(cy + hh, MAX_LAT_DEG)
    if hard_bounds is not None:
        west, east = max(west, hard_bounds.west_deg_east), min(east, hard_bounds.east_deg_east)
        south, north = max(south, hard_bounds.south_deg), min(north, hard_bounds.north_deg)
    if not (west < b.west_deg_east or east > b.east_deg_east or south < b.south_deg or north > b.north_deg):
        raise RegionPlanningError("hard_boundary", "region cannot grow further inside the allowed bounds")
    return plan.model_copy(update={
        "bounds": BoundingBox(west_deg_east=west, south_deg=south, east_deg_east=east, north_deg=north),
        "attempt": plan.attempt + 1,
        "rationale": [*plan.rationale, f"Expanded {factor:g}x about the centre (attempt {plan.attempt + 1} of {MAX_ATTEMPTS})."],
    })
