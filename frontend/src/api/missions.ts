// Client for the mission-planning endpoint, and the mapping from a backend mission plan to the dashboard's Mission.
//
// The backend picks real science targets of the analysis and routes every leg on the analysed terrain (463 m cells).
// Geometry arrives as longitude/latitude; the dashboard works in canvas pixels, so it is converted with the same projection
// the routes use. Slopes and elevation gain come from each leg's own elevation profile.
import type { LonLat } from '../types/contracts';
import type { MissionLeg, MissionPlanRequest, MissionPlanResult } from '../types/missionPlan';
import type { Mission, Obstacle, Pt, Stats, Target } from '../types/ui';
import { API_BASE } from './analysis';
import { ANALYSIS_VERSION, RoutingError, obstacleToBlockedArea } from './routing';
import { WALK_KMH, lonLatToPx, pxToLonLat } from '../utils/geo';

async function call<T>(path: string, method: 'GET' | 'POST', body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail ?? b); } catch { /* keep the status text */ }
    throw new RoutingError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const planMissionRemote = (req: MissionPlanRequest) => call<MissionPlanResult>('/mission-plans', 'POST', req);
export const getMissionPlan = (id: string) => call<MissionPlanResult>(`/mission-plans/${id}`, 'GET');

export interface MissionInputs {
  missionId: string; analysisId: string; start: Pt; base: Pt; targetIds: string[];
  slope: number; maxKm: number; oxyH: number; reserveMin: number; examMin: number; maxSites: number; obs: Obstacle[];
}

const ll = (p: Pt): LonLat => { const c = pxToLonLat(p); return { latitude_deg: c.latitude_deg, longitude_deg_east: c.longitude_deg_east }; };

export function buildMissionRequest(a: MissionInputs): MissionPlanRequest {
  const total = Math.max(1, a.oxyH * 60);
  return {
    mission_id: a.missionId, analysis_id: a.analysisId, analysis_version: ANALYSIS_VERSION, start: ll(a.start), base: ll(a.base),
    constraints: {
      max_slope_deg: Math.min(45, Math.max(1, a.slope)), max_distance_m: a.maxKm * 1000, max_duration_min: total,
      traversal_speed_m_per_min: (WALK_KMH * 1000) / 60, examination_time_per_target_min: a.examMin,
      max_target_count: Math.max(1, a.maxSites), return_to_base: true, reserve_fraction: Math.min(0.9, Math.max(0, a.reserveMin / total)),
      unknown_terrain_policy: 'exclude', required_target_ids: [],
    },
    // science and confidence rasters do not exist yet, so those weights stay at zero instead of being silently ignored
    preferences: { distance: 1, slope: 2, roughness: 2, elevation_gain: 1, hazard: 3, science: 0, confidence: 0 },
    blocked_areas: a.obs.map(obstacleToBlockedArea),
    target_ids: a.targetIds.length ? a.targetIds : null,
  };
}

/** Dashboard stats for one leg: distances in km, slopes from the leg's own elevation profile. */
export function legStats(leg: MissionLeg, o: { slope: number; speed: number }): Stats {
  const n = leg.geometry.length;
  const p: Pt[] = leg.geometry.map((q) => { const px = lonLatToPx(q); return { x: px.x, y: px.y }; });
  const prof = leg.elevation_profile;
  const dist = prof.length === n ? prof.map((q) => q.distance_m) : leg.geometry.map((_, i) => (i / Math.max(1, n - 1)) * leg.metrics.distance_m);
  const known = prof.length === n ? prof.map((q) => (q.valid && q.elevation_m != null ? q.elevation_m : null)) : leg.geometry.map(() => null);
  let last: number | null = null;
  const filled = known.map((v) => { if (v != null) last = v; return last; });
  const first = filled.find((v) => v != null) ?? 0;
  const el = filled.map((v) => v ?? first);
  const cum = dist.map((d) => (d - dist[0]) / 1000);
  const sl = [0], over: number[] = [];
  let up = 0, dn = 0, mx = 0, sum = 0;
  for (let k = 1; k < n; k++) {
    const run = (cum[k] - cum[k - 1]) * 1000, dz = el[k] - el[k - 1];
    const ok = known[k] != null && known[k - 1] != null && run > 0;
    const s = ok ? Math.atan(Math.abs(dz) / run) * (180 / Math.PI) : 0;
    sl.push(dz < 0 ? -s : s);
    if (dz > 0) up += dz; else dn -= dz;
    mx = Math.max(mx, s); sum += s;
    if (s > o.slope) over.push(k);
  }
  const d = cum[n - 1] ?? 0;
  return { p, d, up, dn, mx, av: sum / Math.max(1, n - 1), cum, el, sl, over, t: (d * 1000) / o.speed };
}

/** The backend's plan as the dashboard's Mission (legs to targets, the return to base, and why targets were left out). */
export function toDashboardMission(res: MissionPlanResult, targets: Target[], o: { slope: number; speed?: number }): Mission {
  const opts = { slope: o.slope, speed: o.speed ?? (WALK_KMH * 1000) / 60 };
  const byId = new Map(targets.map((t) => [t.id, t]));
  const ex = res.excluded.flatMap((e) => { const t = byId.get(e.target_id); return t ? [{ t, r: e.message }] : []; });
  if (!res.feasible) {
    const why = res.conflict_details.map((d) => d.message).join(' ') || res.constraint_conflicts.join(', ') || 'No mission fits the limits.';
    return { feasible: false, msg: why, legs: [], ex };
  }
  const legs = [...res.stops].sort((a, b) => a.order - b.order).flatMap((s) => { const t = byId.get(s.target_id); return t && s.leg.geometry.length >= 2 ? [{ t, s: legStats(s.leg, opts) }] : []; });
  const ret = res.return_leg && res.return_leg.geometry.length >= 2 ? legStats(res.return_leg, opts) : undefined;
  if (!legs.length) return { feasible: false, msg: 'The plan has no stops the dashboard can show.', legs: [], ex };
  return { feasible: true, legs, ret, ex };
}
