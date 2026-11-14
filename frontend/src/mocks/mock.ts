/**
 * MOCK BACKEND. Everything in this file is demo logic. Replace each function with a call to the
 * FastAPI contract (routes, profiles, warnings, targets, layer metadata, data quality).
 * Nothing here is a NASA measurement.
 */
import type { Dest, Mission, Obstacle, Pt, Region, Route, Stats, Summary, Target } from '../types/ui';
import { COSTS, alternatives, elevation, slopeAt, KM_PER_PX } from '../utils/geo';

export const STAGES = ['Determine region', 'Discover NASA products', 'Check cache', 'Download', 'Process / align layers', 'Identify targets', 'Calculate routes', 'Optimize itinerary', 'Complete'];
export const ROUTE_COLORS = ['#2dd4d0', '#e8aa3c', '#b99cf0'];

export interface RouteArgs { from: Pt; dest: Dest; wps: Pt[]; base: Pt; ret: boolean; slope: number; obs: Obstacle[] }

export function planRoutes(a: RouteArgs): Route[] {
  const ctx = { slope: a.slope, obs: a.obs };
  const meta = [['short', 'Shortest'], ['safe', 'Safest terrain'], ['bal', 'Balanced']] as const;
  const A = alternatives([a.from, ...a.wps, a.dest], meta.map(([k]) => COSTS[k]), ctx);
  const out: Route[] = [];
  A.forEach((alt, i) => {
    if (!alt) return;
    const key = meta[i][0];
    let ret: Stats | null = null;
    if (a.ret) {
      // Return path is calculated independently, not by reversing the outbound geometry.
      const r = alternatives([a.dest, a.base], [COSTS[key]], ctx, [-alt.bend])[0] ?? alternatives([a.dest, a.base], [COSTS[key]], ctx)[0];
      ret = r ? r.s : null;
    }
    out.push({ k: key, n: meta[i][1], c: ROUTE_COLORS[i], out: alt.s, ret, bend: alt.bend });
  });
  return out;
}

export interface MissionArgs {
  from: Pt; base: Pt; targets: Target[]; oxy: number; res: number; exam: number;
  maxSites: number; slope: number; maxd: number; obs: Obstacle[];
}

export function planMission(a: MissionArgs): Mission {
  const ctx = { slope: a.slope, obs: a.obs }, budget = a.oxy * 60 - a.res, reasons: Record<string, string> = {};
  const f = (s: Stats) => s.d + s.mx * 1.5;
  let cur: Pt = a.from, used = 0, left = [...a.targets];
  const order: { t: Target; s: Stats }[] = [];
  while (order.length < a.maxSites && left.length) {
    let best: { t: Target; s: Stats; sc: number } | null = null;
    for (const t of [...left]) {
      const r = alternatives([cur, t], [f], ctx)[0], bk = alternatives([t, a.base], [f], ctx)[0];
      let why = '';
      if (!r || !bk) why = 'no feasible route';
      else if (r.s.mx > a.slope) why = `leg slope ${r.s.mx.toFixed(0)}° exceeds ${a.slope}° limit`;
      else if (r.s.d > a.maxd) why = 'exceeds maximum distance';
      else if (used + r.s.t + a.exam + bk.s.t > budget) why = 'does not fit time budget';
      if (why || !r) { reasons[t.id] = why || 'no feasible route'; left = left.filter((x) => x !== t); continue; }
      const sc = t.score / (r.s.t + a.exam);
      if (!best || sc > best.sc) best = { t, s: r.s, sc };
    }
    if (!best) break;
    order.push({ t: best.t, s: best.s });
    used += best.s.t + a.exam; cur = best.t;
    const chosen = best.t;
    left = left.filter((x) => x !== chosen);
  }
  left.forEach((t) => { reasons[t.id] = order.length >= a.maxSites ? 'maximum number of sites reached' : 'lower priority'; });
  const ex = a.targets.filter((t) => !order.some((o) => o.t === t)).map((t) => ({ t, r: reasons[t.id] ?? 'lower priority' }));
  if (!order.length) {
    return { feasible: false, legs: [], ex, msg: 'No feasible mission: ' + (ex.length ? ex.map((e) => `${e.t.id} ${e.r}`).join('; ') : 'no candidate targets found') + '. Increase oxygen time or slope limit.' };
  }
  const rt = alternatives([cur, a.base], [f], ctx)[0];
  if (!rt) return { feasible: false, legs: [], ex, msg: 'No feasible return path to base with the reported obstacles.' };
  return { feasible: true, legs: order.map((o) => ({ t: o.t, s: o.s })), ret: rt.s, ex };
}

export function discoverTargets(r: Region): Target[] {
  let s = 7;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const cats = ['Hydrated mineral candidate', 'Clay signature candidate', 'Carbonate candidate', 'Layered outcrop', 'Thermal anomaly'];
  return cats.map((cat, i) => ({
    id: 'T-0' + (i + 1), cat,
    x: Math.round(r.x + 30 + rnd() * (r.w - 60)), y: Math.round(r.y + 30 + rnd() * (r.h - 60)),
    score: Math.round(55 + rnd() * 40), conf: rnd() > 0.5 ? 'Medium' : 'Low',
  }));
}

export function summarizeRegion(r: Region, slopeLimit: number): Summary {
  let mn = 1e9, mx = -1e9, sl = 0, hz = 0, n = 0;
  for (let x = r.x; x < r.x + r.w; x += 20) for (let y = r.y; y < r.y + r.h; y += 20) {
    const e = elevation(x, y), s = slopeAt(x, y);
    mn = Math.min(mn, e); mx = Math.max(mx, e); sl += s; if (s > slopeLimit) hz++; n++;
  }
  return { w: r.w * KM_PER_PX, h: r.h * KM_PER_PX, mn, mx, sl: sl / n, hz: (hz / n) * 100 };
}
