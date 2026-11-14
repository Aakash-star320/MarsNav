import type { Region } from '../types/ui';

/** The part of the planning canvas currently visible on the dashboard map (canvas pixels, 20 m each). */
let visible: Region | null = null;
export const setViewport = (r: Region) => { visible = r; };
export const getViewport = (): Region | null => visible;

/** Largest side of an automatic terrain read: 2,250 px x 20 m = 45 km, about 2,000 km2 (the analyzer accepts 2,500 km2). */
export const MAX_AUTO_SIDE_PX = 2250;

/** The visible area, shrunk around its centre if it is larger than one analysis may cover. */
export function autoTerrainRegion(v: Region): Region {
  const w = Math.min(v.w, MAX_AUTO_SIDE_PX), h = Math.min(v.h, MAX_AUTO_SIDE_PX);
  return { x: Math.round(v.x + (v.w - w) / 2), y: Math.round(v.y + (v.h - h) / 2), w: Math.round(w), h: Math.round(h) };
}
