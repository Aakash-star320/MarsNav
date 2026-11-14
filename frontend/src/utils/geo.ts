import type { Obstacle, Pt, Region, Stats } from '../types/ui';

export const KM_PER_PX = 0.02; // 1 map px = 20 m (demo scale)
export const WALK_KMH = 2;     // simulation assumption, not certified

/** Demo terrain model. Replace with backend DEM sampling. */
export const elevation = (x: number, y: number) =>
  -2500 + 380 * Math.sin(x / 80) + 300 * Math.cos(y / 60) + 250 * Math.exp(-((x - 600) ** 2 + (y - 220) ** 2) / 15000);

export const slopeAt = (x: number, y: number) =>
  Math.atan(Math.hypot((elevation(x + 1, y) - elevation(x - 1, y)) / 40, (elevation(x, y + 1) - elevation(x, y - 1)) / 40)) * 57.3;

export const fmtCoord = (p?: Pt | null) =>
  p ? `${(77.4 + p.x * 0.01).toFixed(2)}°E, ${(18.4 - p.y * 0.01).toFixed(2)}°N` : 'not set';
export const fmtDuration = (m: number) => `${Math.floor(m / 60)} h ${Math.round(m % 60)} min`;

export function segment(a: Pt, b: Pt, bend: number, n = 30): Pt[] {
  const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1, px = -dy / l, py = dx / l, out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, o = Math.sin(Math.PI * t) * bend;
    out.push({ x: Math.max(5, Math.min(795, a.x + dx * t + px * o)), y: Math.max(5, Math.min(495, a.y + dy * t + py * o)) });
  }
  return out;
}

export function chain(P: Pt[], bend: number): Pt[] {
  let out: Pt[] = [];
  for (let i = 0; i < P.length - 1; i++) {
    const s = segment(P[i], P[i + 1], bend);
    out = out.concat(i ? s.slice(1) : s);
  }
  return out;
}

export function computeStats(p: Pt[], limit: number): Stats {
  let d = 0, up = 0, dn = 0, mx = 0, sm = 0;
  const cum = [0], el = [elevation(p[0].x, p[0].y)], sl = [0], over: number[] = [];
  for (let i = 1; i < p.length; i++) {
    const l = Math.hypot(p[i].x - p[i - 1].x, p[i].y - p[i - 1].y) * KM_PER_PX;
    const e = elevation(p[i].x, p[i].y), dz = e - el[i - 1];
    const s = l ? Math.atan(Math.abs(dz) / (l * 1000)) * 57.3 : 0;
    d += l; cum.push(d); el.push(e); sl.push(dz < 0 ? -s : s);
    if (dz > 0) up += dz; else dn -= dz;
    mx = Math.max(mx, s); sm += s;
    if (s > limit) over.push(i);
  }
  return { p, d, up, dn, mx, av: sm / Math.max(1, p.length - 1), cum, el, sl, over, t: (d / WALK_KMH) * 60 };
}

export const isBlocked = (p: Pt[], obs: Obstacle[]) =>
  obs.some((o) => p.some((q) => Math.hypot(q.x - o.x, q.y - o.y) < o.r));

const BENDS = [-160, -120, -80, -40, 0, 40, 80, 120, 160];
export type CostFn = (s: Stats) => number;
export interface Alt { bend: number; s: Stats }
export interface PlanCtx { slope: number; obs: Obstacle[] }

export const COSTS: Record<'short' | 'safe' | 'bal', CostFn> = {
  short: (s) => s.d,
  safe: (s) => s.mx * 10 + s.d * 0.5 + s.over.length * 5,
  bal: (s) => s.d + s.mx * 1.5 + s.av * 2,
};

/** Best candidate path per cost function, never reusing a candidate, skipping obstacle-blocked paths. */
export function alternatives(P: Pt[], costs: CostFn[], ctx: PlanCtx, exclude: number[] = []): (Alt | undefined)[] {
  const cand: Alt[] = BENDS.filter((b) => !exclude.includes(b))
    .map((b) => ({ bend: b, s: computeStats(chain(P, b), ctx.slope) }))
    .filter((x) => !isBlocked(x.s.p, ctx.obs));
  const used: Alt[] = [];
  return costs.map((f) => {
    const r = cand.filter((x) => !used.includes(x)).sort((a, b) => f(a.s) - f(b.s))[0];
    if (r) used.push(r);
    return r;
  });
}

/** 0 = detailed regional data, 1 = moderate, 2 = coarse global data (demo zones). */
export function zoneOf(p: Pt, region: Region | null, base: Pt): 0 | 1 | 2 {
  const R = region ?? { x: base.x - 200, y: base.y - 150, w: 400, h: 300 };
  if (p.x >= R.x && p.x <= R.x + R.w && p.y >= R.y && p.y <= R.y + R.h) return 0;
  return p.x >= R.x - 150 && p.x <= R.x + R.w + 150 && p.y >= R.y - 120 && p.y <= R.y + R.h + 120 ? 1 : 2;
}
export const coarseShare = (s: Stats, region: Region | null, base: Pt) =>
  s.p.filter((q) => zoneOf(q, region, base) === 2).length / s.p.length;
