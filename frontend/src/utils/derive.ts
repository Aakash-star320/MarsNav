import type { DataState, Pt, Stats, Target, Warning } from '../types/ui';
import { computeStats, coarseShare, fmtDuration, zoneOf } from './geo';

export const RETURN_COLOR = '#9aa7bd';
const LEG_COLORS = ['#2dd4d0', '#e8aa3c', '#b99cf0'];

export interface Seg { s: Stats; c: string; n: string; dashed?: boolean; t?: Target }
export interface Combined { s: Stats; b: number[]; sg: Seg[] }
export interface BudgetPart { n: string; m: number; c: string }
export interface Budget { a: BudgetPart[]; T: number; ok: boolean; u: number }

/** Path segments of the currently active route or mission. */
export function segsOf(s: DataState): Seg[] {
  if (s.mode === 'mission' && s.mission?.feasible && s.mission.ret) {
    return [
      ...s.mission.legs.map((l, i) => ({ s: l.s, c: LEG_COLORS[i % 3], n: `Leg ${i + 1} → ${l.t.label ?? l.t.id}`, t: l.t })),
      { s: s.mission.ret, c: RETURN_COLOR, dashed: true, n: 'Return to base' },
    ];
  }
  const r = s.routes[s.sel];
  if (s.mode === 'route' && r) {
    return [{ s: r.out, c: r.c, n: 'Outbound' }, ...(r.ret ? [{ s: r.ret, c: RETURN_COLOR, dashed: true, n: 'Return (independent)' }] : [])];
  }
  return [];
}

export function combined(s: DataState): Combined | null {
  const sg = segsOf(s);
  if (!sg.length) return null;
  let p: Pt[] = [];
  const b: number[] = [];
  sg.forEach((x) => { b.push(p.length); p = p.concat(p.length ? x.s.p.slice(1) : x.s.p); });
  return { s: computeStats(p, s.slope), b, sg };
}

export function budgetOf(s: DataState): Budget | null {
  const sg = segsOf(s);
  if (!sg.length) return null;
  const T = s.oxy * 60, m = s.mission;
  let a: BudgetPart[];
  if (s.mode === 'mission' && m?.feasible && m.ret) {
    const tr = m.legs.map((l) => l.s.t);
    a = [
      { n: 'Outbound', m: tr[0], c: '#2dd4d0' },
      { n: 'Between sites', m: tr.slice(1).reduce((x, y) => x + y, 0), c: '#b99cf0' },
      { n: 'Examination', m: m.legs.length * s.exam, c: '#c0653a' },
      { n: 'Return', m: m.ret.t, c: RETURN_COLOR },
      { n: 'Reserve', m: s.res, c: '#e5645f' },
    ];
  } else {
    a = [
      { n: 'Outbound', m: sg[0].s.t, c: '#2dd4d0' },
      { n: 'Return', m: sg[1] ? sg[1].s.t : 0, c: RETURN_COLOR },
      { n: 'Reserve', m: s.res, c: '#e5645f' },
    ];
  }
  const u = a.reduce((x, y) => x + y.m, 0);
  return { a: [...a, { n: 'Unused', m: Math.max(0, T - u), c: '#2a3a57' }], T, ok: u <= T, u };
}

export function warningsOf(s: DataState): Warning[] {
  const w: Warning[] = [];
  if (s.mission && !s.mission.feasible && s.mission.msg) w.push({ k: 'bad', t: s.mission.msg });
  const c = combined(s);
  if (!c) return w;
  const st = c.s, o = st.over;
  for (let i = 0, n = 0; i < o.length && n < 5; n++) {
    let j = i;
    while (j + 1 < o.length && o[j + 1] === o[j] + 1) j++;
    let mx = 0;
    for (let q = i; q <= j; q++) mx = Math.max(mx, Math.abs(st.sl[o[q]]));
    w.push({ k: 'warn', t: `Steep segment at ${st.cum[o[i]].toFixed(1)} km: up to ${mx.toFixed(1)}° (limit ${s.slope}°). Measured from demo DEM; not a safety guarantee.`, at: st.p[o[i]] });
    i = j + 1;
  }
  const b = budgetOf(s);
  if (b && !b.ok) w.push({ k: 'bad', t: `Time budget exceeded by ${fmtDuration(b.u - b.T)}: shorten route, reduce sites or add oxygen time.` });
  const cp = st.p.find((q) => zoneOf(q, s.region, s.base) === 2);
  if (cp) w.push({ k: 'warn', t: `Route crosses coarse-resolution terrain (${(coarseShare(st, s.region, s.base) * 100).toFixed(0)}% of path). Slopes there are uncertain; resampling does not add detail.`, at: cp });
  if (s.summary && s.cats.spec) w.push({ k: 'info', t: 'Spectral coverage is partial (62%, demo value). Missing coverage is not confirmed absence of minerals.' });
  s.obs.forEach((o) => w.push({ k: 'info', t: 'Reported obstacle (user-reported, not dataset-derived).', at: o }));
  return w;
}
