import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useMissionStore } from '../store/missionStore';
import { analyzeAreaOnMap, AnalysisError, applyMapPackage, waitForAnalysis, type MapPackage } from './analysis';

const AOI = { west_deg_east: 77.0, south_deg: 18.1, east_deg_east: 77.8, north_deg: 18.8 };
const layer = (kind: string, id: string) => ({
  layer: { id, kind, uri: `http://x/${kind}.png`, bounds: AOI, resolution_m_per_px: 463, valid_percent: 100, units: 'm', dataset_ids: [], style_hint: {}, availability: 'available', limitations: [] },
  projection: 'MARS:CANONICAL_ANGULAR', format: 'image', source: 'MOLA', synthetic: false, coverage: 'available', legend: kind, colors: ['#000000', '#ffffff'],
});
const PKG = {
  analysis_id: 'a1', notes: [],
  layers: [layer('elevation', 'L1'), layer('slope', 'L2')],
  dem: { version: 1, synthetic: false, width: 2, height: 2, bounds: AOI, projection: { kind: 'mars-local-equirectangular', radius_m: 3396190, latitude_origin_deg: 18.45, longitude_origin_deg_east: 77.4 },
    affine: [0, 100, 0, 0, 0, -100], sample_registration: 'point', vertical_datum: 'x', units: 'm', values: [1, 2, 3, null] },
} as unknown as MapPackage;

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

beforeEach(() => useMissionStore.getState().reset());
afterEach(() => vi.restoreAllMocks());

describe('analysis client', () => {
  it('loads a map package into the mission store and shows the elevation layer', () => {
    applyMapPackage(PKG);
    const s = useMissionStore.getState();
    expect(s.layers.map((l) => l.layer.kind)).toEqual(['elevation', 'slope']);
    expect(s.dem?.width).toBe(2);
    expect(s.layerSettings.L1.visible).toBe(true);
    expect(s.layerSettings.L2.visible).toBe(false);
  });

  it('runs create -> poll -> fetch and reports progress', async () => {
    const seen: string[] = [];
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input); calls.push(`${init?.method ?? 'GET'} ${url.replace(/^.*\/api\/v1/, '')}`);
      if (url.endsWith('/analyses')) return reply({ id: 'a1', stage: 'queued', progress_percent: 0, message: 'Queued', warnings: [] }, 202);
      if (url.endsWith('/analyses/a1')) return reply(calls.filter((c) => c === 'GET /analyses/a1').length < 2
        ? { id: 'a1', stage: 'terrain', progress_percent: 80, message: 'Deriving', warnings: [] }
        : { id: 'a1', stage: 'completed', progress_percent: 100, message: 'done', warnings: ['coarse data'] });
      return reply(PKG);
    });
    vi.spyOn(globalThis, 'setTimeout').mockImplementation(((fn: () => void) => { fn(); return 0; }) as typeof setTimeout);
    const { warnings } = await analyzeAreaOnMap(AOI, (j) => seen.push(j.stage));
    expect(warnings).toEqual(['coarse data']);
    expect(seen).toEqual(['terrain', 'completed']);
    expect(calls[0]).toBe('POST /analyses');
    expect(useMissionStore.getState().layers).toHaveLength(2);
  });

  it('surfaces a failed job with its error code and loads nothing', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() =>
      reply({ id: 'a2', stage: 'failed', progress_percent: 25, message: 'region exceeds the 2500 km2 analysis limit', warnings: [], error_code: 'area_limit' }));
    await expect(waitForAnalysis('a2')).rejects.toMatchObject({ code: 'area_limit', message: expect.stringContaining('2500 km2') });
    expect(useMissionStore.getState().layers).toHaveLength(0);
  });

  it('turns HTTP errors into readable messages', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ detail: 'analysis not found' }, 404));
    await expect(waitForAnalysis('zzz')).rejects.toBeInstanceOf(AnalysisError);
    await expect(waitForAnalysis('zzz')).rejects.toThrow('analysis not found');
  });
});
