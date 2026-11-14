import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from './dashboardStore';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const BOUNDS = { west_deg_east: 77.41, south_deg: 18.4, east_deg_east: 77.5, north_deg: 18.48 };
const layer = (kind: string) => ({ layer: { id: kind, kind, uri: `http://api/x/${kind}.png`, bounds: BOUNDS }, projection: 'MARS:CANONICAL_ANGULAR', format: 'image' });
const STATS = {
  area_km2: 60, rows: 18, cols: 20, cells_total: 360, cells_valid: 360, valid_percent: 100, cell_size_x_m: 439, cell_size_y_m: 463,
  elevation_min_m: -2700, elevation_max_m: -1700, slope_mean_deg: 2.5, slope_max_deg: 12, slope_limit_deg: 20, slope_denominator_cells: 340,
  slope_exceedance_cells: 17, slope_exceedance_fraction: 0.05, science_candidates: 1, notes: [],
};
const TARGET = {
  id: 'b0a1c2d3-0000-4000-8000-000000000001', title: 'Hydrated hydroxylated-mineral candidate (D2300 with BD1900R2)', objective_category: 'hydrated_minerals',
  relevance_score: 0.64, confidence: 'low', rank_explanation: 'rank = 0.7 x mean evidence ...', location: { latitude_deg: 18.45, longitude_deg_east: 77.45 },
  evidence: [{ statement: 'CRISM obs: mean D2300 = 0.0114', measured: true }, { statement: 'Candidate rule: ...', measured: false }],
};
const PACKAGE = { analysis_id: 'a1', layers: [layer('elevation'), layer('slope'), layer('science')], dem: null, statistics: STATS, science_targets: [TARGET], notes: [] };
const QUEUED = (id: string) => ({ id, stage: 'queued', progress_percent: 0, message: 'Queued', warnings: [] });

beforeEach(() => {
  useStore.getState().reset();
  useStore.setState({ online: true, job: null, err: '' });
  useStore.getState().setRegion({ x: 100, y: 100, w: 200, h: 100 });
});
afterEach(() => vi.restoreAllMocks());

describe('Analyze Region uses the real analysis', () => {
  it('runs the job, then shows real statistics, targets with evidence, and real layers', async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input).replace(/^.*\/api\/v1/, '');
      calls.push(`${init?.method ?? 'GET'} ${url}`);
      if (url === '/analyses') return reply(QUEUED('a1'), 202);
      if (url === '/analyses/a1') return reply({ id: 'a1', stage: 'completed', progress_percent: 100, message: 'done', warnings: ['coarse data'] });
      return reply(PACKAGE);
    });
    useStore.getState().analyze();
    expect(useStore.getState().job?.real).toBe(true);
    await vi.waitFor(() => expect(useStore.getState().real).not.toBeNull());
    const s = useStore.getState();
    expect(s.job).toBeNull();
    expect(calls[0]).toBe('POST /analyses');
    expect(s.summary).toMatchObject({ mn: -2700, mx: -1700, sl: 2.5, hz: 5 });
    expect(s.summary?.w).toBeCloseTo(4, 6);                                  // 200 px x 20 m
    expect(s.real?.warnings).toEqual(['coarse data']);
    expect(s.real?.layers.science?.href).toContain('science.png');
    expect(s.targets).toHaveLength(1);
    expect(s.targets[0]).toMatchObject({ label: 'C-01', score: 64, conf: 'Low' });
    expect(s.targets[0].evidence?.[0]).toContain('D2300');
    expect(s.layers.elev.on).toBe(true);
    expect(s.layers.spec.on).toBe(true);
  });

  it('cancelling stops the run, asks the backend to cancel, and ignores a late result', async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input).replace(/^.*\/api\/v1/, '');
      calls.push(`${init?.method ?? 'GET'} ${url}`);
      return url === '/analyses' ? reply(QUEUED('a2'), 202) : reply({});
    });
    useStore.getState().analyze();
    useStore.getState().cancelJob();
    await vi.waitFor(() => expect(calls).toContain('POST /analyses/a2/cancel'));
    expect(useStore.getState().job).toBeNull();
    expect(useStore.getState().real).toBeNull();
    expect(useStore.getState().err).toMatch(/Cancelled/);
  });

  it('says so when the analysis service cannot be reached, and does not fake a result', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed to fetch'));
    useStore.getState().analyze();
    await vi.waitFor(() => expect(useStore.getState().job).toBeNull());
    expect(useStore.getState().err).toMatch(/Cannot reach the analysis service/);
    expect(useStore.getState().real).toBeNull();
    expect(useStore.getState().summary).toBeNull();
  });

  it('refuses to run offline, without calling the network', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    useStore.setState({ online: false });
    useStore.getState().analyze();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(useStore.getState().err).toMatch(/offline/i);
  });

  it('turns a too-large region into a clear message', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input).replace(/^.*\/api\/v1/, '');
      if (url === '/analyses') return reply(QUEUED('a3'), 202);
      return reply({ id: 'a3', stage: 'failed', progress_percent: 10, message: 'region exceeds the limit', warnings: [], error_code: 'area_limit' });
    });
    useStore.getState().analyze();
    await vi.waitFor(() => expect(useStore.getState().err).toMatch(/too large/));
    expect(useStore.getState().job).toBeNull();
  });

  it('changing the region discards the previous real analysis', () => {
    useStore.setState({ real: { id: 'x', hazardBase: '', layers: { elevation: { href: '', bounds: BOUNDS }, slope: { href: '', bounds: BOUNDS } }, stats: STATS, warnings: [], notes: [] } as never });
    useStore.getState().setRegion({ x: 0, y: 0, w: 50, h: 50 });
    expect(useStore.getState().real).toBeNull();
  });
});
