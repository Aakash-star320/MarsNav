import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from './dashboardStore';
import { buildRouteRequest, obstacleToBlockedArea, toDashboardRoutes } from '../api/routing';
import { pxToLonLat } from '../utils/geo';
import type { RouteResult } from '../types/contracts';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const ll = (x: number, y: number) => { const c = pxToLonLat({ x, y }); return { latitude_deg: c.latitude_deg, longitude_deg_east: c.longitude_deg_east }; };
const BOUNDS = { west_deg_east: pxToLonLat({ x: 0, y: 0 }).longitude_deg_east, north_deg: pxToLonLat({ x: 0, y: 0 }).latitude_deg, east_deg_east: pxToLonLat({ x: 800, y: 500 }).longitude_deg_east, south_deg: pxToLonLat({ x: 800, y: 500 }).latitude_deg };

/** A straight route of `n` points from (x0,y0) to (x1,y1) at 20 m per canvas pixel, climbing 2 m per point. */
function route(x0: number, y0: number, x1: number, y1: number, n = 6, id = 'r-main'): Pick<RouteResult, 'geometry' | 'elevation_profile'> & { id: string } {
  const geometry = Array.from({ length: n }, (_, k) => ll(x0 + ((x1 - x0) * k) / (n - 1), y0 + ((y1 - y0) * k) / (n - 1)));
  const step = Math.hypot(x1 - x0, y1 - y0) * 20 / (n - 1);
  return { id, geometry, elevation_profile: geometry.map((_, k) => ({ distance_m: k * step, elevation_m: -2600 + 2 * k, valid: true })) };
}
function result(over: Partial<RouteResult> = {}): RouteResult {
  const m = route(100, 100, 300, 200);
  return {
    id: m.id, feasible: true, analysis_id: 'a1', analysis_version: 'analysis/1', request_version: 'route-request/abc', geometry: m.geometry, waypoints: [],
    metrics: { distance_m: 4472, estimated_duration_min: 134, max_slope_deg: 1, elevation_gain_m: 10, confidence: 'low' }, segments: [], elevation_profile: m.elevation_profile,
    alternatives: [{ id: 'r-safe', label: 'Safest terrain', geometry: route(100, 100, 300, 200, 8, 'r-safe').geometry, elevation_profile: route(100, 100, 300, 200, 8, 'r-safe').elevation_profile, warnings: [] }],
    target_ids: [], warnings: ['Coarse 463 m data: broad planning only.'], constraint_conflicts: [], conflict_details: [], ...over,
  } as RouteResult;
}

const REAL = { id: 'a1', missionId: 'm1', hazardBase: '', layers: { elevation: { href: '', bounds: BOUNDS }, slope: { href: '', bounds: BOUNDS } }, stats: {}, warnings: [], notes: [] } as never;

beforeEach(() => {
  useStore.getState().reset();
  useStore.setState({ online: true, job: null, err: '', real: REAL, mode: 'route', start: { x: 100, y: 100 }, dest: { x: 300, y: 200 }, wps: [], ret: false });
});
afterEach(() => vi.restoreAllMocks());

describe('real routes from the routing service', () => {
  it('maps a backend route to dashboard routes: shortest/safest/balanced order, stats from the elevation profile, ids kept', () => {
    const routes = toDashboardRoutes(result(), 'bal', { slope: 20, speed: 33.3, ret: false, dest: { x: 300, y: 200 } });
    expect(routes.map((r) => r.k)).toEqual(['safe', 'bal']);                     // only the routes that exist; ordered like the simulated planner
    const bal = routes.find((r) => r.k === 'bal')!;
    expect(bal.src).toEqual({ id: 'r-main', replanId: 'r-main', version: 'route-request/abc' });
    expect(bal.out.p).toHaveLength(6);
    expect(bal.out.p[0].x).toBeCloseTo(100, 3);
    expect(bal.out.d).toBeCloseTo(4.472, 2);                                      // km, from the profile's own distances
    expect(bal.out.up).toBeCloseTo(10, 6);                                        // 5 steps x 2 m
    expect(bal.out.dn).toBe(0);
    expect(bal.out.el[0]).toBe(-2600);
    expect(bal.out.cum[0]).toBe(0);
    expect(bal.out.t).toBeCloseTo((bal.out.d * 1000) / 33.3, 3);
    const safe = routes.find((r) => r.k === 'safe')!;
    expect(safe.src?.id).toBe('r-safe');
    expect(safe.src?.replanId).toBe('r-main');                                    // a replan always goes through the requested route
  });

  it('splits a round trip at the destination into an outbound route and a separately reported return', () => {
    const out = route(100, 100, 300, 200, 6), back = route(300, 200, 100, 100, 6);
    const geometry = [...out.geometry, ...back.geometry.slice(1)];
    const total = out.elevation_profile.at(-1)!.distance_m;
    const profile = [...out.elevation_profile, ...back.elevation_profile.slice(1).map((p) => ({ ...p, distance_m: p.distance_m + total }))];
    const [r] = toDashboardRoutes(result({ geometry, elevation_profile: profile, alternatives: [] }), 'bal', { slope: 20, speed: 33.3, ret: true, dest: { x: 300, y: 200 } });
    expect(r.out.p.at(-1)!.x).toBeCloseTo(300, 3);
    expect(r.ret).not.toBeNull();
    expect(r.ret!.p[0].x).toBeCloseTo(300, 3);
    expect(r.ret!.p.at(-1)!.x).toBeCloseTo(100, 3);
    expect(r.ret!.cum[0]).toBe(0);                                                // distances restart for the return leg
  });

  it('an infeasible route produces no dashboard routes', () => {
    expect(toDashboardRoutes(result({ feasible: false }), 'bal', { slope: 20, speed: 33, ret: false, dest: { x: 1, y: 1 } })).toEqual([]);
  });

  it('builds the request from the dashboard state: lon/lat points, limits in metres, obstacles as blocked boxes, no unsupported weights', () => {
    const req = buildRouteRequest({ missionId: 'm1', analysisId: 'a1', start: { x: 100, y: 100 }, dest: { x: 300, y: 200 }, wps: [], base: { x: 120, y: 360 }, preset: 'safe', slope: 20, ret: true, maxKm: 50, oxyH: 4, reserveMin: 30, examMin: 20, speedMPerMin: 33.3, obs: [{ x: 200, y: 150, r: 35 }] });
    expect(req).toMatchObject({ mission_id: 'm1', analysis_id: 'a1', analysis_version: 'analysis/1', preset: 'safest' });
    expect(req.start.longitude_deg_east).toBeCloseTo(ll(100, 100).longitude_deg_east, 9);
    expect(req.constraints).toMatchObject({ max_slope_deg: 20, max_distance_m: 50000, max_duration_min: 210, return_to_base: true, unknown_terrain_policy: 'exclude' });
    expect(req.preferences).toMatchObject({ science: 0, confidence: 0 });
    const b = obstacleToBlockedArea({ x: 200, y: 150, r: 35 }).bounds;
    expect(b.east_deg_east).toBeGreaterThan(b.west_deg_east);
    expect(b.north_deg).toBeGreaterThan(b.south_deg);
    expect(req.blocked_areas).toHaveLength(1);
    expect(req.waypoints).toEqual([]);
    expect(req.base?.longitude_deg_east).toBeCloseTo(ll(120, 360).longitude_deg_east, 9);
  });

  it('Generate Routes calls the routing service when an analysis exists, and labels the routes as real', async () => {
    let body: Record<string, unknown> = {};
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input).endsWith('/routes')) { body = JSON.parse(String(init?.body)); return reply(result()); }
      return reply({});
    });
    useStore.getState().generate();
    await vi.waitFor(() => expect(useStore.getState().routes.length).toBeGreaterThan(0));
    const s = useStore.getState();
    expect(body.analysis_id).toBe('a1');
    expect(s.routeSource).toBe('real');
    expect(s.routeNotes).toContain('Coarse 463 m data: broad planning only.');
    expect(s.job).toBeNull();
    expect(s.routes.every((r) => r.src)).toBe(true);
  });

  it('an infeasible answer is shown in plain words and leaves no route behind', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply(result({ feasible: false, geometry: [], elevation_profile: [], alternatives: [],
      conflict_details: [{ code: 'max_slope_exceeded', message: 'Every way there crosses ground steeper than the maximum slope.', affected_target_ids: [] }] })));
    useStore.getState().generate();
    await vi.waitFor(() => expect(useStore.getState().err).toMatch(/No feasible route/));
    expect(useStore.getState().err).toContain('steeper than the maximum slope');
    expect(useStore.getState().routes).toEqual([]);
  });

  it('points outside the analysed area are refused with an explanation, and nothing is sent', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    useStore.setState({ real: { ...(REAL as object), layers: { elevation: { href: '', bounds: { ...BOUNDS, east_deg_east: pxToLonLat({ x: 150, y: 0 }).longitude_deg_east } }, slope: { href: '', bounds: BOUNDS } } } as never });
    useStore.getState().generate();
    expect(useStore.getState().err).toMatch(/inside the analysed area/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('waypoints and the base are sent to the routing service, so those routes are real too', async () => {
    let body: Record<string, any> = {};
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input).endsWith('/routes')) { body = JSON.parse(String(init?.body)); return reply(result()); }
      return reply({});
    });
    useStore.setState({ wps: [{ x: 150, y: 120 }, { x: 250, y: 160 }], ret: true, base: { x: 120, y: 110 } });
    useStore.getState().generate();
    await vi.waitFor(() => expect(useStore.getState().routes.length).toBeGreaterThan(0));
    expect(body.waypoints).toHaveLength(2);
    expect(body.waypoints[0].longitude_deg_east).toBeCloseTo(ll(150, 120).longitude_deg_east, 9);
    expect(body.base.latitude_deg).toBeCloseTo(ll(120, 110).latitude_deg, 9);
    expect(body.constraints.return_to_base).toBe(true);
    expect(useStore.getState().routeSource).toBe('real');
    expect(useStore.getState().routeNotes.join(' ')).not.toMatch(/start point/);        // the return now ends at the Base
  });

  it('no base is sent without a return trip, and waypoints or a base outside the analysed area are refused', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    expect(buildRouteRequest({ missionId: 'm1', analysisId: 'a1', start: { x: 1, y: 1 }, dest: { x: 2, y: 2 }, wps: [], base: { x: 5, y: 5 }, preset: 'bal', slope: 20, ret: false, maxKm: 50, oxyH: 4, reserveMin: 30, examMin: 0, speedMPerMin: 33, obs: [] }).base).toBeUndefined();
    useStore.setState({ real: { ...(REAL as object), layers: { elevation: { href: '', bounds: { ...BOUNDS, east_deg_east: pxToLonLat({ x: 400, y: 0 }).longitude_deg_east } }, slope: { href: '', bounds: BOUNDS } } } as never, wps: [{ x: 600, y: 120 }] });
    useStore.getState().generate();
    expect(useStore.getState().err).toMatch(/waypoint must be inside the analysed area/);
    useStore.setState({ wps: [], ret: true, base: { x: 700, y: 400 }, err: '' });
    useStore.getState().generate();
    expect(useStore.getState().err).toMatch(/Base must be inside the analysed area/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('more waypoints than the contract allows stay on the simulated planner', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({}));
    useStore.setState({ wps: Array.from({ length: 11 }, (_, k) => ({ x: 120 + k * 10, y: 120 })) });
    useStore.getState().generate();
    expect(fetchSpy.mock.calls.every(([u]) => !String(u).includes('/routes'))).toBe(true);
    expect(useStore.getState().routeSource).not.toBe('real');
  });

  it('an unreachable service is reported honestly', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed to fetch'));
    useStore.getState().generate();
    await vi.waitFor(() => expect(useStore.getState().err).toMatch(/Cannot reach the routing service/));
    expect(useStore.getState().job).toBeNull();
    expect(useStore.getState().routes).toEqual([]);
  });

  it('without an analysis the simulated planner is used and the routes are labelled simulated', () => {
    useStore.setState({ real: null });
    useStore.getState().generate();
    expect(useStore.getState().routeSource).not.toBe('real');
  });

  it('a new obstacle is sent to the replan endpoint, not planned from scratch', async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input).replace(/^.*\/api\/v1/, '');
      calls.push(`${init?.method ?? 'GET'} ${url}`);
      return reply(result({ id: url.includes('replan') ? 'r-new' : 'r-main' }));
    });
    useStore.getState().generate();
    await vi.waitFor(() => expect(useStore.getState().routes.length).toBeGreaterThan(0));
    useStore.setState({ obs: [{ x: 200, y: 150, r: 35 }] });
    useStore.getState().replan();
    await vi.waitFor(() => expect(calls.some((c) => c.includes('/replan'))).toBe(true));
    expect(calls).toContain('POST /routes/r-main/replan');
    await vi.waitFor(() => expect(useStore.getState().routes.some((r) => r.src?.id === 'r-new')).toBe(true));
  });
});
