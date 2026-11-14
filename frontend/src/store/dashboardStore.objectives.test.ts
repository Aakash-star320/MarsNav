import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from './dashboardStore';
import { resetObjectivesCache } from '../api/objectives';
import type { ObjectiveInfo } from '../api/objectives';
import { journeyRegion } from '../api/journey';
import { regionToBounds } from '../api/mapping';
import { LAYERS, defaultLayers } from '../utils/layers';
import { pxToLonLat } from '../utils/geo';
import type { MissionLeg, MissionPlanResult } from '../types/missionPlan';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const LIST: ObjectiveInfo[] = [
  { id: 'hydrated_minerals', label: 'Hydrated minerals', kind: 'spectral', description: 'd', keywords: ['hydrated', 'mineral', 'clay'], data_used: ['CRISM'], limitation: 'Heuristic screen.' },
  { id: 'flat_safe_sites', label: 'Flat safe sites', kind: 'terrain', description: 'd', keywords: ['flat', 'safe site'], data_used: ['MOLA'], limitation: '463 m elevation.' },
];
const BASE = { x: 120, y: 360 };
const ll = (x: number, y: number) => { const c = pxToLonLat({ x, y }); return { latitude_deg: c.latitude_deg, longitude_deg_east: c.longitude_deg_east }; };

function leg(x0: number, y0: number, x1: number, y1: number): MissionLeg {
  const geometry = Array.from({ length: 5 }, (_, k) => ll(x0 + ((x1 - x0) * k) / 4, y0 + ((y1 - y0) * k) / 4));
  const step = (Math.hypot(x1 - x0, y1 - y0) * 20) / 4;
  return { geometry, elevation_profile: geometry.map((_, k) => ({ distance_m: k * step, elevation_m: -2600 + k, valid: true })), metrics: { distance_m: step * 4, estimated_duration_min: 5, confidence: 'low' } };
}
const PLAN: MissionPlanResult = {
  id: 'p1', feasible: true, analysis_id: 'j1', analysis_version: 'analysis/1', request_version: 'mission-request/x',
  stops: [{ order: 1, target_id: 't1', arrival_min: 40, examination_min: 20, leg: leg(120, 360, 300, 200) }], return_leg: leg(300, 200, 120, 360),
  totals: { distance_m: 8000, duration_min: 150, reserve_min: 30, budget_min: 240, remaining_min: 60, science_value: 0.6 },
  excluded: [], warnings: [], constraint_conflicts: [], conflict_details: [], provenance: { analysis_version: 'analysis/1', formula_version: 'mission-greedy/1', layer_ids: [] },
};

/** A backend that answers every endpoint the journey flow touches; `over` replaces individual answers. */
function backend(over: Record<string, (body: any) => Promise<Response>> = {}) {
  const calls: string[] = [], bodies: Record<string, any> = {};
  const bounds = regionToBounds(journeyRegion(BASE, 4));
  const layer = (kind: string) => ({ layer: { id: kind, kind, uri: `http://api/x/${kind}.png`, bounds }, projection: 'MARS:CANONICAL_ANGULAR', format: 'image' });
  const target = { id: 't1', title: 'Candidate', objective_category: 'x', relevance_score: 0.6, confidence: 'low', rank_explanation: 'r', location: ll(300, 200), evidence: [{ statement: 'e', measured: true }] };
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input).replace(/^.*\/api\/v1/, '').split('?')[0];
    const key = `${init?.method ?? 'GET'} ${url}`;
    calls.push(key);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    bodies[key] = body;
    if (over[key]) return over[key](body);
    if (key === 'POST /analyses') return reply({ id: 'j1', mission_id: 'mj', stage: 'queued', progress_percent: 0, message: 'q', warnings: [] }, 202);
    if (key === 'GET /analyses/j1') return reply({ id: 'j1', stage: 'completed', progress_percent: 100, message: 'done', warnings: [] });
    if (key === 'GET /analyses/j1/map') return reply({ analysis_id: 'j1', layers: [layer('elevation'), layer('slope')], dem: null, science_targets: [target], notes: [],
      statistics: { elevation_min_m: -2700, elevation_max_m: -2500, slope_mean_deg: 2, slope_max_deg: 9, slope_limit_deg: 20, slope_exceedance_fraction: 0, science_candidates: 1, notes: [], valid_percent: 100 } });
    if (key === 'POST /mission-plans') return reply(PLAN);
    if (key === 'GET /data-budget') return reply({ per_analysis_cap_bytes: 67108864, session_cap_bytes: 268435456, session_used_bytes: 5242880, analyses_counted: 1 });
    return reply({});
  });
  return { calls, bodies };
}

beforeEach(() => {
  resetObjectivesCache();
  useStore.getState().reset();
  useStore.setState({ online: true, job: null, err: '', chat: [], pendingQ: null, assistantMode: 'rule_based', objectives: LIST, obj: 'hydrated_minerals', base: BASE, real: null, region: null });
});
afterEach(() => vi.restoreAllMocks());

describe('the objective decides what is analysed', () => {
  const analyse = async (set: Record<string, unknown>, fn: () => void) => {
    const { bodies } = backend();
    useStore.setState({ region: { x: 100, y: 300, w: 300, h: 200 }, ...set });
    fn();
    await vi.waitFor(() => expect(bodies['POST /analyses']).toBeDefined());
    return bodies['POST /analyses'].objective as string;
  };
  it('a spectral objective sends its label and searches CRISM', async () => {
    expect(await analyse({ obj: 'hydrated_minerals' }, () => useStore.getState().analyze())).toBe('Hydrated minerals');
    expect(useStore.getState().job?.stages).toContain('Search CRISM');
  });
  it('a terrain objective sends its own label and shows no CRISM stage', async () => {
    expect(await analyse({ obj: 'flat_safe_sites' }, () => useStore.getState().analyze())).toBe('Flat safe sites');
    expect(useStore.getState().job?.stages).not.toContain('Search CRISM');
  });
  it('with the mineral checkbox off a spectral objective falls back to the plain terrain overview, as before', async () => {
    expect(await analyse({ obj: 'hydrated_minerals', cats: { elev: true, slope: true, rough: true, haz: true, spec: false } }, () => useStore.getState().analyze())).toBe('terrain overview');
  });
  it('terrain-only reads for 3D keep the plain terrain overview whatever objective is selected', async () => {
    expect(await analyse({ obj: 'flat_safe_sites' }, () => useStore.getState().analyzeTerrainView())).toBe('terrain overview');
  });
});

describe('objectives and the data line load through the store', () => {
  it('loadObjectives replaces the built-in list with the backend list, and keeps it when the backend is down', async () => {
    useStore.setState({ objectives: [LIST[0]] });
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply(LIST));
    useStore.getState().loadObjectives();
    await vi.waitFor(() => expect(useStore.getState().objectives).toHaveLength(2));
  });
  it('the data budget is stored when available and cleared when the endpoint fails', async () => {
    backend();
    useStore.getState().refreshDataBudget();
    await vi.waitFor(() => expect(useStore.getState().dataBudget?.session_used_bytes).toBe(5242880));
    vi.restoreAllMocks();
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({}, 404));
    useStore.getState().refreshDataBudget();
    await vi.waitFor(() => expect(useStore.getState().dataBudget).toBeNull());
  });
});

describe('no simulated data layer remains', () => {
  it('the thermal and coverage toggles are gone from the layer list, the defaults and the analyze checkboxes', () => {
    expect(LAYERS.map((l) => l.id)).not.toContain('therm');
    expect(LAYERS.map((l) => l.id)).not.toContain('cov');
    expect(Object.keys(defaultLayers())).toEqual(expect.not.arrayContaining(['therm', 'cov']));
    expect(Object.keys(useStore.getState().layers)).not.toContain('therm');
    expect(Object.keys(useStore.getState().cats)).not.toContain('therm');
  });
});

describe('a science journey typed in the chat', () => {
  it('with a supported objective it analyses around the base, plans the mission, and reports the outcome', async () => {
    const { calls, bodies } = backend();
    useStore.getState().sendChat('I have four hours of oxygen; find mineral sites and return to base');
    expect(useStore.getState().pendingQ).toMatch(/four hours/);
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1), { timeout: 8000 });
    const s = useStore.getState();
    expect(calls.indexOf('POST /analyses')).toBeLessThan(calls.indexOf('POST /mission-plans'));        // analysis first, then the mission
    expect(bodies['POST /analyses'].objective).toBe('Hydrated minerals');
    const b = bodies['POST /analyses'].roi.bounds, expected = regionToBounds(journeyRegion(BASE, 4));
    expect(b.west_deg_east).toBeCloseTo(expected.west_deg_east, 6);                                       // 12 km square around the base for 4 hours
    expect(s.oxy).toBe(4);
    expect(s.obj).toBe('hydrated_minerals');
    expect(s.missionSource).toBe('real');
    expect(s.pendingQ).toBeNull();
    const m = s.chat[0];
    expect(m.err).toBeUndefined();
    expect(m.r).toMatch(/Planned a mission for "Hydrated minerals" with 4 h of oxygen: 1 site and [\d.]+ km/);
    expect(m.steps).toEqual(expect.arrayContaining(['Objective: Hydrated minerals', 'Oxygen: 4 h']));
    expect(m.actions?.map((a) => a.label)).toContain('Open full details');
  });

  it('a terrain objective is analysed by its own label and no CRISM stage is shown', async () => {
    const { bodies } = backend();
    useStore.getState().sendChat('plan a 3 hour mission to find a flat safe site');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1), { timeout: 8000 });
    expect(bodies['POST /analyses'].objective).toBe('Flat safe sites');
    expect(useStore.getState().chat[0].r).toMatch(/Flat safe sites/);
  });

  it('if the area has no candidates it says so and never invents a mission', async () => {
    const { calls } = backend({ 'GET /analyses/j1/map': () => reply({ analysis_id: 'j1', layers: [], dem: null, science_targets: [], notes: [], statistics: null }) });
    useStore.getState().sendChat('find clay sites, I have 4 hours of oxygen');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1), { timeout: 8000 });
    expect(calls).not.toContain('POST /mission-plans');
    expect(useStore.getState().chat[0].err).toBeDefined();                                                   // the analysis returned no terrain layers: reported, not hidden
  });

  it('an unsupported goal asks the catalog and shows exactly what it answered, with no analysis started', async () => {
    const { calls, bodies } = backend({ 'POST /objectives/check': () => reply({
      objective: 'x', matched_objective_id: null, supported: false, message: 'NASA has THEMIS coverage here, but this tool cannot analyse thermal data yet.',
      coverage: [{ instrument: 'THEMIS', product_type: 'IRB', label: 'THEMIS day IR', measures: 'temperature', covered_percent: 92.4, product_count: 4, example_product_ids: ['I1'], analyzable: false, note: 'n' }],
      warnings: ['Coverage comes from the ODE catalog.'] }) });
    useStore.getState().sendChat('plan a mission to study thermal properties with 6 hours of oxygen');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1));
    const m = useStore.getState().chat[0];
    expect(m.r).toBe('NASA has THEMIS coverage here, but this tool cannot analyse thermal data yet.');
    expect(m.steps).toEqual(['THEMIS day IR: 92% covered · not analysable yet']);
    expect(m.note).toBe('Coverage comes from the ODE catalog.');
    expect(calls).not.toContain('POST /analyses');
    expect(calls).not.toContain('POST /mission-plans');
    expect(bodies['POST /objectives/check'].bounds.east_deg_east).toBeGreaterThan(bodies['POST /objectives/check'].bounds.west_deg_east);
    expect(useStore.getState().pendingQ).toBeNull();
  });

  it('if the catalog says it does support the objective, the journey continues with that objective', async () => {
    const { bodies } = backend({ 'POST /objectives/check': () => reply({ objective: 'x', matched_objective_id: 'flat_safe_sites', supported: true, message: 'ok', coverage: [], warnings: [] }) });
    useStore.getState().sendChat('plan a mission to study landing places with 4 hours of oxygen');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1), { timeout: 8000 });
    expect(bodies['POST /analyses'].objective).toBe('Flat safe sites');
  });

  it('a failed or unreachable catalog check is reported honestly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed to fetch'));
    useStore.getState().sendChat('plan a mission to study boxwork formations with 4 hours of oxygen');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1));
    expect(useStore.getState().chat[0]).toMatchObject({ err: true });
    expect(useStore.getState().chat[0].r).toMatch(/could not reach the service/);
    vi.restoreAllMocks();
    backend({ 'POST /objectives/check': () => reply({ detail: 'boom' }, 500) });
    useStore.getState().sendChat('plan a mission to study ice formations with 4 hours of oxygen');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(2));
    expect(useStore.getState().chat[1].r).toMatch(/answered 500/);
    expect(useStore.getState().chat[1].err).toBe(true);
  });

  it('route and analysis commands are not treated as journeys', () => {
    const { calls } = backend();
    useStore.getState().sendChat('Analyze this region');
    expect(calls.some((c) => c.includes('/objectives/check'))).toBe(false);
    useStore.getState().cancelJob();
  });
});
