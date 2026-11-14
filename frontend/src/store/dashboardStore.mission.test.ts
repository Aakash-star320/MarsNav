import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from './dashboardStore';
import { pxToLonLat } from '../utils/geo';
import type { MissionLeg, MissionPlanResult } from '../types/missionPlan';
import type { Target } from '../types/ui';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const ll = (x: number, y: number) => { const c = pxToLonLat({ x, y }); return { latitude_deg: c.latitude_deg, longitude_deg_east: c.longitude_deg_east }; };
const P0 = pxToLonLat({ x: 0, y: 0 }), P1 = pxToLonLat({ x: 800, y: 500 });
const BOUNDS = { west_deg_east: P0.longitude_deg_east, north_deg: P0.latitude_deg, east_deg_east: P1.longitude_deg_east, south_deg: P1.latitude_deg };
const REAL = { id: 'a1', missionId: 'm1', hazardBase: '', layers: { elevation: { href: '', bounds: BOUNDS }, slope: { href: '', bounds: BOUNDS } }, stats: {}, warnings: [], notes: [] } as never;

function leg(x0: number, y0: number, x1: number, y1: number): MissionLeg {
  const geometry = Array.from({ length: 5 }, (_, k) => ll(x0 + ((x1 - x0) * k) / 4, y0 + ((y1 - y0) * k) / 4));
  const step = (Math.hypot(x1 - x0, y1 - y0) * 20) / 4;
  return { geometry, elevation_profile: geometry.map((_, k) => ({ distance_m: k * step, elevation_m: -2600 + k, valid: true })), metrics: { distance_m: step * 4, estimated_duration_min: 5, confidence: 'low' } };
}
const TARGETS: Target[] = [{ id: 't1', cat: 'x', x: 300, y: 200, score: 60, conf: 'Low', label: 'C-01' }, { id: 't2', cat: 'x', x: 450, y: 120, score: 40, conf: 'Low', label: 'C-02' }];
const PLAN: MissionPlanResult = {
  id: 'p1', feasible: true, analysis_id: 'a1', analysis_version: 'analysis/1', request_version: 'mission-request/x',
  stops: [{ order: 1, target_id: 't1', arrival_min: 40, examination_min: 20, leg: leg(120, 360, 300, 200) }], return_leg: leg(300, 200, 120, 360),
  totals: { distance_m: 8000, duration_min: 150, reserve_min: 30, budget_min: 240, remaining_min: 60, science_value: 0.6 },
  excluded: [{ target_id: 't2', code: 'does_not_fit_time_budget', message: 'Does not fit the time budget.' }],
  warnings: [], constraint_conflicts: [], conflict_details: [], provenance: { analysis_version: 'analysis/1', formula_version: 'mission-greedy/1', layer_ids: [] },
};

beforeEach(() => {
  useStore.getState().reset();
  useStore.setState({ online: true, job: null, err: '', real: REAL, targets: TARGETS, mode: 'mission', base: { x: 120, y: 360 } });
});
afterEach(() => vi.restoreAllMocks());

describe('Plan Mission with a real analysis', () => {
  it('calls the mission planner with the dashboard state and shows its legs, return and excluded targets as a real mission', async () => {
    let body: Record<string, any> = {};
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input).endsWith('/mission-plans')) { body = JSON.parse(String(init?.body)); return reply(PLAN); }
      return reply({});
    });
    useStore.getState().plan();
    expect(useStore.getState().job?.real).toBe(true);
    await vi.waitFor(() => expect(useStore.getState().mission).not.toBeNull());
    const s = useStore.getState();
    expect(body).toMatchObject({ mission_id: 'm1', analysis_id: 'a1', target_ids: ['t1', 't2'] });
    expect(body.constraints).toMatchObject({ max_duration_min: 240, max_target_count: 3, examination_time_per_target_min: 20 });
    expect(s.missionSource).toBe('real');
    expect(s.job).toBeNull();
    expect(s.mission?.feasible).toBe(true);
    expect(s.mission?.legs.map((l) => l.t.id)).toEqual(['t1']);
    expect(s.mission?.ret?.p.at(-1)?.x).toBeCloseTo(120, 3);
    expect(s.mission?.ex).toEqual([{ t: TARGETS[1], r: 'Does not fit the time budget.' }]);
  });

  it('an infeasible plan is shown in plain words and is still labelled as coming from the service', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ ...PLAN, feasible: false, stops: [], return_leg: null,
      conflict_details: [{ code: 'no_science_targets', message: 'This analysis has no science targets.', affected_target_ids: [] }] }));
    useStore.getState().plan();
    await vi.waitFor(() => expect(useStore.getState().mission).not.toBeNull());
    expect(useStore.getState().mission).toMatchObject({ feasible: false, msg: 'This analysis has no science targets.' });
    expect(useStore.getState().missionSource).toBe('real');
  });

  it('an unreachable service is reported honestly and no mission is made up', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed to fetch'));
    useStore.getState().plan();
    await vi.waitFor(() => expect(useStore.getState().err).toMatch(/Cannot reach the routing service/));
    expect(useStore.getState().job).toBeNull();
    expect(useStore.getState().mission).toBeNull();
  });

  it('a service error message is shown as it is', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ detail: 'analysis a1 is running, not completed' }, 409));
    useStore.getState().plan();
    await vi.waitFor(() => expect(useStore.getState().err).toMatch(/Mission planning failed: analysis a1 is running/));
    expect(useStore.getState().job).toBeNull();
  });

  it('cancelling while the service works drops the late answer', async () => {
    let release: (r: Response) => void = () => undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise<Response>((r) => { release = r; }));
    useStore.getState().plan();
    useStore.getState().cancelJob();
    release(new Response(JSON.stringify(PLAN), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    await new Promise((r) => setTimeout(r, 30));
    expect(useStore.getState().mission).toBeNull();
  });
});

describe('Plan Mission stays simulated when the real planner cannot be used', () => {
  const noNetwork = () => vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({}));
  const planned = () => vi.waitFor(() => expect(useStore.getState().mission).not.toBeNull(), { timeout: 8000 });

  it('without an analysis the simulated planner runs, labelled simulated, with no network call', async () => {
    const spy = noNetwork();
    useStore.setState({ real: null });
    useStore.getState().plan();
    await planned();
    expect(useStore.getState().missionSource).toBe('simulated');
    expect(spy).not.toHaveBeenCalled();
  }, 10000);

  it('with an analysis that has no targets it also stays simulated', async () => {
    const spy = noNetwork();
    useStore.setState({ targets: [] });
    useStore.getState().plan();
    await planned();
    expect(useStore.getState().missionSource).toBe('simulated');
    expect(spy.mock.calls.every(([u]) => !String(u).includes('/mission-plans'))).toBe(true);
  }, 10000);

  it('offline it stays simulated and does not call the service', async () => {
    const spy = noNetwork();
    useStore.setState({ online: false });
    useStore.getState().plan();
    await planned();
    expect(useStore.getState().missionSource).toBe('simulated');
    expect(spy).not.toHaveBeenCalled();
  }, 10000);
});
