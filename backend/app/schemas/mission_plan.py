"""Mission-plan contract: choose science targets that fit a time budget, visit them, return to base.

Kept in its own module (not in ``contracts.py``) while the shape settles; import from here directly.
All geometry is planetocentric degrees, east-positive longitude. Times are minutes, distances metres.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from .contracts import (
    BlockedArea,
    ConstraintConflict,
    ElevationProfilePoint,
    LonLat,
    MissionConstraints,
    RouteMetrics,
    RouteProvenance,
    WeightPreferences,
)


class MissionPlanRequest(BaseModel):
    mission_id: UUID
    analysis_id: UUID
    analysis_version: str
    start: LonLat
    base: LonLat
    # ``max_duration_min`` is the total oxygen time BEFORE the reserve; ``reserve_fraction`` of it is kept back.
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    preferences: WeightPreferences = Field(default_factory=WeightPreferences)
    blocked_areas: list[BlockedArea] = Field(default_factory=list)
    target_ids: list[UUID] | None = None          # None: consider every science target of the analysis


class MissionLeg(BaseModel):
    geometry: list[LonLat] = Field(default_factory=list)
    metrics: RouteMetrics
    elevation_profile: list[ElevationProfilePoint] = Field(default_factory=list)


class MissionStop(BaseModel):
    order: int = Field(ge=1)
    target_id: UUID
    arrival_min: float = Field(ge=0)               # time since the start at which the target is reached
    examination_min: float = Field(ge=0)
    leg: MissionLeg                                # the way here from the previous stop (or the start)


class MissionTotals(BaseModel):
    distance_m: float = Field(ge=0)
    duration_min: float = Field(ge=0)              # travel plus examinations, including the return leg
    reserve_min: float = Field(ge=0)
    budget_min: float | None = None                # None when no duration limit was given
    remaining_min: float | None = None             # budget - reserve - duration; None without a limit
    science_value: float | None = None             # sum of the visited targets' relevance scores (heuristic, not a measurement)


class ExcludedTarget(BaseModel):
    target_id: UUID
    code: str
    message: str


class MissionPlanResult(BaseModel):
    id: UUID
    feasible: bool
    analysis_id: UUID
    analysis_version: str
    request_version: str
    stops: list[MissionStop] = Field(default_factory=list)
    return_leg: MissionLeg | None = None
    totals: MissionTotals
    excluded: list[ExcludedTarget] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    constraint_conflicts: list[str] = Field(default_factory=list)
    conflict_details: list[ConstraintConflict] = Field(default_factory=list)
    provenance: RouteProvenance
