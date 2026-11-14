// Boundary adapters: the dashboard/map keep a pixel-space view model (types/ui.ts); everything that
// crosses the API boundary uses the shared contracts (types/contracts.ts). Coordinates are
// planetocentric latitude and east-positive longitude.
import type { BoundingBox, RegionOfInterest, RouteResult, ScienceTarget } from '../types/contracts';
import type { Pt, Region, Route, Target } from '../types/ui';
import { lonLatToPx, pxToLonLat } from '../utils/geo';

export const regionToBounds = (r: Region): BoundingBox => {
  const nw = pxToLonLat({ x: r.x, y: r.y }), se = pxToLonLat({ x: r.x + r.w, y: r.y + r.h });
  return { west_deg_east: nw.longitude_deg_east, south_deg: se.latitude_deg, east_deg_east: se.longitude_deg_east, north_deg: nw.latitude_deg };
};

export const boundsToRegion = (b: BoundingBox): Region => {
  const nw = lonLatToPx({ latitude_deg: b.north_deg, longitude_deg_east: b.west_deg_east });
  const se = lonLatToPx({ latitude_deg: b.south_deg, longitude_deg_east: b.east_deg_east });
  return { x: nw.x, y: nw.y, w: se.x - nw.x, h: se.y - nw.y };
};

export const regionToRoi = (r: Region, name = 'Selected region', analysis_margin_m = 0): RegionOfInterest =>
  ({ name, bounds: regionToBounds(r), analysis_margin_m });

const CONFIDENCE = { high: 'high', medium: 'medium', low: 'low' } as const;

export const toScienceTarget = (t: Target): ScienceTarget => ({
  id: t.id, location: pxToLonLat(t), title: t.cat, objective_category: t.cat, relevance_score: t.score,
  confidence: CONFIDENCE[t.conf.toLowerCase() as keyof typeof CONFIDENCE] ?? 'unknown', evidence: [],
});

export const fromScienceTarget = (t: ScienceTarget): Target =>
  ({ id: t.id, cat: t.title, ...lonLatToPx(t.location), score: t.relevance_score, conf: t.confidence[0].toUpperCase() + t.confidence.slice(1) });

export const toRouteResult = (r: Route, id: string = r.k): RouteResult => ({
  id, feasible: true, geometry: r.out.p.map(pxToLonLat), waypoints: [],
  metrics: { distance_m: r.out.d * 1000, estimated_duration_min: r.out.t, max_slope_deg: r.out.mx, elevation_gain_m: r.out.up, confidence: 'unknown' },
  segments: [], elevation_profile: r.out.cum.map((d, i) => ({ distance_m: d * 1000, elevation_m: r.out.el[i], valid: true })),
  alternatives: [], target_ids: [], warnings: [], constraint_conflicts: [], conflict_details: [],
});

export type { Pt };

/** A real science target as the dashboard shows it: pixel position, 0-100 score, evidence statements. */
export const toDashboardTarget = (t: ScienceTarget, index: number): Target => {
  const p = lonLatToPx(t.location);
  return {
    id: t.id, label: `C-${String(index + 1).padStart(2, '0')}`, cat: t.title, x: Math.round(p.x), y: Math.round(p.y),
    score: Math.round(t.relevance_score * 100), conf: t.confidence[0].toUpperCase() + t.confidence.slice(1),
    evidence: t.evidence.map((e) => e.statement), rank: t.rank_explanation ?? undefined, objective: t.objective_category,
  };
};
