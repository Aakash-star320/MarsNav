// Types of the mission-planning endpoint (POST /mission-plans, GET /mission-plans/{id}).
// The planner picks real science targets of an analysis that fit the oxygen budget, visits them in order, and returns to the base.
import type { BlockedArea, ConstraintConflict, ElevationProfilePoint, LonLat, MissionConstraints, RouteMetrics, RouteProvenance, UUID, WeightPreferences } from './contracts';

export type MissionPlanRequest = {
  mission_id: UUID; analysis_id: UUID; analysis_version: string; start: LonLat; base: LonLat;
  /** `max_duration_min` is the total oxygen time before the reserve; `reserve_fraction` applies to it. */
  constraints: MissionConstraints; preferences: WeightPreferences; blocked_areas: BlockedArea[];
  /** null = consider every science target of the analysis. */
  target_ids: UUID[] | null;
};

export type MissionLeg = { geometry: LonLat[]; metrics: RouteMetrics; elevation_profile: ElevationProfilePoint[] };
export type MissionStop = { order: number; target_id: UUID; arrival_min: number; examination_min: number; leg: MissionLeg };
export type MissionTotals = { distance_m: number; duration_min: number; reserve_min: number; budget_min: number; remaining_min: number; science_value: number | null };
export type ExcludedTarget = { target_id: UUID; code: string; message: string };

export type MissionPlanResult = {
  id: UUID; feasible: boolean; analysis_id: UUID; analysis_version: string; request_version: string;
  stops: MissionStop[]; return_leg: MissionLeg | null; totals: MissionTotals; excluded: ExcludedTarget[];
  warnings: string[]; constraint_conflicts: string[]; conflict_details: ConstraintConflict[]; provenance: RouteProvenance;
};
