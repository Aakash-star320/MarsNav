import { describe, expect, it } from 'vitest';
import { buildMissionRequest, legStats, toDashboardMission } from './missions';
import { pxToLonLat } from '../utils/geo';
import type { MissionLeg, MissionPlanResult } from '../types/missionPlan';
import type { Target } from '../types/ui';

const ll = (x: number, y: number) => { const c = pxToLonLat({ x, y }); return { latitude_deg: c.latitude_deg, longitude_deg_east: c.longitude_deg_east }; };
/** A straight leg of n points, 20 m per canvas pixel, climbing `climb` m per point. */
function leg(x0: number, y0: number, x1: number, y1: number, n = 5, climb = 2): MissionLeg {
  const geometry = Array.from({ length: n }, (_, k) => ll(x0 + ((x1 - x0) * k) / (n - 1), y0 + ((y1 - y0) * k) / (n - 1)));
  const step = (Math.hypot(x1 - x0, y1 - y0) * 20) / (n - 1);
  return { geometry, elevation_profile: geometry.map((_, k) => ({ distance_m: k * step, elevation_m: -2600 + climb * k, valid: true })),
           metrics: { distance_m: step * (n - 1), estimated_duration_min: 10, confidence: 'low' } };
}
const T = (id: string, x: number, y: number, label: string): Target => ({ id, cat: 'x', x, y, score: 50, conf: 'Low', label });
const TARGETS = [T('t1', 300, 200, 'C-01'), T('t2', 400, 100, 'C-02'), T('t3', 500, 300, 'C-03')];
const PROV = { analysis_version: 'analysis/1', formula_version: 'mission-greedy/1', layer_ids: [] };
function plan(over: Partial<MissionPlanResult> = {}): MissionPlanResult {
  return {
    id: 'p1', feasible: true, analysis_id: 'a1', analysis_version: 'analysis/1', request_version: 'mission-request/x',
    stops: [{ order: 2, target_id: 't2', arrival_min: 90, examination_min: 20, leg: leg(300, 200, 400, 100) }, { order: 1, target_id: 't1', arrival_min: 40, examination_min: 20, leg: leg(120, 360, 300, 200) }],
    return_leg: leg(400, 100, 120, 360), totals: { distance_m: 9000, duration_min: 200, reserve_min: 30, budget_min: 240, remaining_min: 10, science_value: 0.9 },
    excluded: [{ target_id: 't3', code: 'does_not_fit_time_budget', message: 'Does not fit the time budget.' }],
    warnings: [], constraint_conflicts: [], conflict_details: [], provenance: PROV, ...over,
  };
}

describe('mission request', () => {
  it('is built from the dashboard state: lon/lat points, oxygen as minutes, reserve as a fraction, obstacles as blocked boxes', () => {
    const req = buildMissionRequest({ missionId: 'm1', analysisId: 'a1', start: { x: 120, y: 360 }, base: { x: 120, y: 360 }, targetIds: ['t1', 't2'], slope: 20, maxKm: 50, oxyH: 4, reserveMin: 30, examMin: 20, maxSites: 3, obs: [{ x: 200, y: 150, r: 35 }] });
    expect(req).toMatchObject({ mission_id: 'm1', analysis_id: 'a1', analysis_version: 'analysis/1', target_ids: ['t1', 't2'] });
    expect(req.base.longitude_deg_east).toBeCloseTo(ll(120, 360).longitude_deg_east, 9);
    expect(req.constraints).toMatchObject({ max_duration_min: 240, reserve_fraction: 0.125, examination_time_per_target_min: 20, max_target_count: 3, max_slope_deg: 20, max_distance_m: 50000, return_to_base: true, unknown_terrain_policy: 'exclude' });
    expect(req.constraints.traversal_speed_m_per_min).toBeCloseTo(33.33, 1);
    expect(req.preferences).toMatchObject({ science: 0, confidence: 0 });
    expect(req.blocked_areas).toHaveLength(1);
  });

  it('keeps the reserve fraction inside [0, 0.9] and asks for every target when none are listed', () => {
    const base = { missionId: 'm', analysisId: 'a', start: { x: 1, y: 1 }, base: { x: 1, y: 1 }, slope: 20, maxKm: 50, examMin: 20, maxSites: 3, obs: [] };
    expect(buildMissionRequest({ ...base, targetIds: [], oxyH: 1, reserveMin: 600 }).constraints.reserve_fraction).toBe(0.9);
    expect(buildMissionRequest({ ...base, targetIds: [], oxyH: 4, reserveMin: -5 }).constraints.reserve_fraction).toBe(0);
    expect(buildMissionRequest({ ...base, targetIds: [], oxyH: 4, reserveMin: 30 }).target_ids).toBeNull();
  });
});

describe('mission plan to dashboard mission', () => {
  it('maps stops in order to legs with real stats, the return leg, and excluded targets with the reason', () => {
    const m = toDashboardMission(plan(), TARGETS, { slope: 20 });
    expect(m.feasible).toBe(true);
    expect(m.legs.map((l) => l.t.id)).toEqual(['t1', 't2']);                       // sorted by `order`, not by the order received
    const first = m.legs[0].s;
    expect(first.p[0].x).toBeCloseTo(120, 3);
    expect(first.p.at(-1)!.x).toBeCloseTo(300, 3);
    expect(first.d).toBeCloseTo((Math.hypot(180, 160) * 20) / 1000, 3);          // km, from the profile's distances
    expect(first.up).toBeCloseTo(8, 6);                                           // 4 steps x 2 m
    expect(first.dn).toBe(0);
    expect(first.cum[0]).toBe(0);
    expect(first.t).toBeCloseTo((first.d * 1000) / 33.33, 1);
    expect(m.ret!.p[0].x).toBeCloseTo(400, 3);
    expect(m.ret!.p.at(-1)!.x).toBeCloseTo(120, 3);
    expect(m.ex).toEqual([{ t: TARGETS[2], r: 'Does not fit the time budget.' }]);
  });

  it('an infeasible plan is a plain message, and unknown targets are ignored rather than invented', () => {
    const bad = toDashboardMission(plan({ feasible: false, stops: [], return_leg: null, conflict_details: [{ code: 'no_science_targets', message: 'This analysis has no science targets.', affected_target_ids: [] }] }), TARGETS, { slope: 20 });
    expect(bad).toMatchObject({ feasible: false, msg: 'This analysis has no science targets.', legs: [] });
    const stray = toDashboardMission(plan({ stops: [{ order: 1, target_id: 'not-ours', arrival_min: 1, examination_min: 1, leg: leg(1, 1, 5, 5) }], excluded: [] }), TARGETS, { slope: 20 });
    expect(stray.feasible).toBe(false);
    expect(stray.legs).toEqual([]);
  });

  it('slopes come from the leg profile; steps over the limit are flagged; a missing elevation is not turned into a slope', () => {
    const steep = leg(0, 0, 10, 0, 4, 40);                                         // 40 m per 66 m: far above 20 degrees
    expect(legStats(steep, { slope: 20, speed: 33 }).over.length).toBeGreaterThan(0);
    const gap = leg(0, 0, 10, 0, 4, 2);
    gap.elevation_profile[2] = { distance_m: gap.elevation_profile[2].distance_m, valid: false };
    const s = legStats(gap, { slope: 20, speed: 33 });
    expect(s.sl[2]).toBe(0);
    expect(s.sl[3]).toBe(0);
    expect(s.el.every(Number.isFinite)).toBe(true);
  });
});
