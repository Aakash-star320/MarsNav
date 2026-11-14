import type { Region } from '../types/ui';

/** The part of the planning canvas currently visible on the dashboard map (canvas pixels, 20 m each). */
let visible: Region | null = null;
const sane = (r: Region) => [r.x, r.y, r.w, r.h].every(Number.isFinite) && r.w > 20 && r.h > 20;
/** Ignores impossible views (a hidden map reports zero size), so the last real view is kept. */
export const setViewport = (r: Region) => { if (sane(r)) visible = r; };
export const getViewport = (): Region | null => visible;
/** The whole planning canvas, used when no usable view is known. */
export const PLANNING_AREA: Region = { x: 0, y: 0, w: 800, h: 500 };

/** Largest side of an automatic terrain read: 2,250 px x 20 m = 45 km, about 2,000 km2 (the analyzer accepts 2,500 km2). */
export const MAX_AUTO_SIDE_PX = 2250;

/** The visible area, shrunk around its centre if it is larger than one analysis may cover. */
export function autoTerrainRegion(v: Region): Region {
  const w = Math.max(50, Math.min(v.w, MAX_AUTO_SIDE_PX)), h = Math.max(50, Math.min(v.h, MAX_AUTO_SIDE_PX));
  return { x: Math.round(v.x + (v.w - w) / 2), y: Math.round(v.y + (v.h - h) / 2), w: Math.round(w), h: Math.round(h) };
}
