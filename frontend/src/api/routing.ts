// Client for the routing endpoints, and the mapping from a backend route to the dashboard's own route format.
//
// The backend plans on the real analysed terrain (463 m cells) and returns longitude/latitude geometry with an
// elevation profile. The dashboard works in canvas pixels, so geometry is converted with the same projection the
// rest of the canvas uses. Slopes and elevation gain shown here come from the route's own elevation profile.
import type { BlockedArea, LonLat, NavigationInstruction, ReplanRequest, RouteRequest, RouteResult } from '../types/contracts';
import type { Obstacle, Preset, Pt, Route, Stats } from '../types/ui';
import { API_BASE } from './analysis';
import { lonLatToPx, pxToLonLat } from '../utils/geo';

/** The analyzer's version tag; the backend answers 409 if the analysis was produced by another version. */
export const ANALYSIS_VERSION = 'analysis/1';
export const ROUTE_COLORS = ['#2dd4d0', '#e8aa3c', '#b99cf0'];

export class RoutingError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

async function call<T>(path: string, method: 'GET' | 'POST', body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail ?? b); } catch { /* keep the status text */ }
    throw new RoutingError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const planRoute = (req: RouteRequest) => call<RouteResult>('/routes', 'POST', req);
export const replanRoute = (id: string, req: ReplanRequest) => call<RouteResult>(`/routes/${id}/replan`, 'POST', req);
export const guideRoute = (routeId: string, position: LonLat, headingDeg: number) =>
  call<NavigationInstruction>('/navigation/guide', 'POST', { route_id: routeId, state: { position, heading_deg_clockwise_from_north: headingDeg } });

const PRESET: Record<Preset, RouteRequest['preset']> = { short: 'shortest', safe: 'safest', bal: 'balanced' };
const KEY_BY_LABEL: Record<string, Preset> = { 'Shortest': 'short', 'Safest terrain': 'safe', 'Balanced': 'bal' };
const ORDER: Preset[] = ['short', 'safe', 'bal'];
const NAME: Record<Preset, string> = { short: 'Shortest', safe: 'Safest terrain', bal: 'Balanced' };

export interface RouteInputs {
  missionId: string; analysisId: string; start: Pt; dest: Pt; wps: Pt[]; base: Pt; preset: Preset; slope: number; ret: boolean;
  maxKm: number; oxyH: number; reserveMin: number; examMin: number; speedMPerMin: number; obs: Obstacle[];
}

/** A reported obstacle (a circle on the canvas) as a blocked box in degrees. */
export function obstacleToBlockedArea(o: Obstacle): BlockedArea {
  const nw = pxToLonLat({ x: o.x - o.r, y: o.y - o.r }), se = pxToLonLat({ x: o.x + o.r, y: o.y + o.r });
  return { bounds: { west_deg_east: nw.longitude_deg_east, south_deg: se.latitude_deg, east_deg_east: se.longitude_deg_east, north_deg: nw.latitude_deg }, reason: 'Reported obstacle' };
}

export function buildRouteRequest(a: RouteInputs): RouteRequest {
  const point = (p: Pt): LonLat => { const c = pxToLonLat(p); return { latitude_deg: c.latitude_deg, longitude_deg_east: c.longitude_deg_east }; };
  const s = pxToLonLat(a.start), d = pxToLonLat(a.dest);
  return {
    mission_id: a.missionId, analysis_id: a.analysisId, analysis_version: ANALYSIS_VERSION,
    start: { latitude_deg: s.latitude_deg, longitude_deg_east: s.longitude_deg_east },
    destination: { latitude_deg: d.latitude_deg, longitude_deg_east: d.longitude_deg_east },
    waypoints: a.wps.map(point),                      // visited in the order given (the contract allows ten)
    ...(a.ret ? { base: point(a.base) } : {}),        // where the return trip ends
    preset: PRESET[a.preset],
    // science and confidence rasters do not exist yet, so those weights are left at zero instead of being silently ignored
    preferences: { distance: 1, slope: 2, roughness: 2, elevation_gain: 1, hazard: 3, science: 0, confidence: 0 },
    constraints: {
      max_slope_deg: Math.min(45, Math.max(1, a.slope)), max_distance_m: a.maxKm * 1000,
      max_duration_min: Math.max(1, a.oxyH * 60 - a.reserveMin), traversal_speed_m_per_min: a.speedMPerMin,
      examination_time_per_target_min: a.examMin, return_to_base: a.ret, reserve_fraction: 0.2, unknown_terrain_policy: 'exclude', required_target_ids: [],
    },
    blocked_areas: a.obs.map(obstacleToBlockedArea),
  };
}

interface Geo { points: LonLat[]; dist: number[]; elev: (number | null)[] }

/** Dashboard stats for a stretch of a route; `from`..`to` are inclusive indices, distances are re-zeroed at `from`. */
function statsFor(g: Geo, from: number, to: number, o: { slope: number; speed: number }): Stats {
  const idx = Array.from({ length: to - from + 1 }, (_, k) => from + k);
  const p: Pt[] = idx.map((i) => { const q = lonLatToPx(g.points[i]); return { x: q.x, y: q.y }; });
  let last: number | null = null;
  const el = idx.map((i) => { const v = g.elev[i]; if (v != null) last = v; return last ?? NaN; });
  const first = el.find((v) => Number.isFinite(v)) ?? 0;
  const elev = el.map((v) => (Number.isFinite(v) ? v : first));
  const cum = idx.map((i) => (g.dist[i] - g.dist[from]) / 1000);
  const sl = [0], over: number[] = [];
  let up = 0, dn = 0, mx = 0, sum = 0;
  for (let k = 1; k < idx.length; k++) {
    const run = (cum[k] - cum[k - 1]) * 1000, dz = elev[k] - elev[k - 1];
    const known = g.elev[idx[k]] != null && g.elev[idx[k - 1]] != null && run > 0;
    const s = known ? Math.atan(Math.abs(dz) / run) * (180 / Math.PI) : 0;
    sl.push(dz < 0 ? -s : s);
    if (dz > 0) up += dz; else dn -= dz;
    mx = Math.max(mx, s); sum += s;
    if (s > o.slope) over.push(k);
  }
  const d = cum[cum.length - 1];
  return { p, d, up, dn, mx, av: sum / Math.max(1, idx.length - 1), cum, el: elev, sl, over, t: (d * 1000) / o.speed };
}

function toRoute(key: Preset, color: number, id: string, replanId: string, version: string, points: LonLat[], profile: RouteResult['elevation_profile'], o: { slope: number; speed: number; ret: boolean; dest: Pt }): Route | null {
  if (points.length < 2) return null;
  const g: Geo = { points, dist: profile.map((q) => q.distance_m), elev: profile.map((q) => (q.valid ? q.elevation_m ?? null : null)) };
  if (g.dist.length !== points.length) return null;
  let split = points.length - 1;                              // with a return trip the geometry is one loop: split it at the destination
  if (o.ret) {
    let best = Infinity;
    points.forEach((q, i) => { const px = lonLatToPx(q), dd = Math.hypot(px.x - o.dest.x, px.y - o.dest.y); if (dd < best) { best = dd; split = i; } });
  }
  const out = statsFor(g, 0, split, o);
  const ret = o.ret && split < points.length - 1 ? statsFor(g, split, points.length - 1, o) : null;
  return { k: key, n: NAME[key], c: ROUTE_COLORS[color], out, ret, bend: 0, src: { id, replanId, version } };
}

/** The requested route plus its alternatives, ordered shortest / safest / balanced like the simulated planner. */
export function toDashboardRoutes(res: RouteResult, requested: Preset, o: { slope: number; speed: number; ret: boolean; dest: Pt }): Route[] {
  if (!res.feasible || !res.request_version) return [];
  const version = res.request_version;
  // every route can be followed by its own id; a replan always goes through the requested route, which then re-plans the comparison
  const all: (Route | null)[] = [toRoute(requested, 0, res.id, res.id, version, res.geometry, res.elevation_profile, o)];
  for (const a of res.alternatives) {
    const key = KEY_BY_LABEL[a.label];
    if (key) all.push(toRoute(key, 0, a.id, res.id, version, a.geometry, a.elevation_profile, o));
  }
  return all.filter((r): r is Route => r !== null).sort((x, y) => ORDER.indexOf(x.k) - ORDER.indexOf(y.k)).map((r, i) => ({ ...r, c: ROUTE_COLORS[i % 3] }));
}

/** Plain-language reasons from an infeasible route. */
export const conflictText = (res: RouteResult) => res.conflict_details.map((d) => d.message).join(' ') || 'No route satisfies the limits.';
