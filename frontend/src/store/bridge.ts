// Keeps the facts the dashboard and the Mars map share in one agreed state.
//
// The dashboard store (dashboardStore.ts) holds a pixel-space view model; the map store
// (missionStore.ts) holds contract types (BoundingBox, LonLat, ScienceTarget, RouteResult). The map
// store is the contract-typed source for these shared facts and this module converts between the two
// with api/mapping.ts. Dashboard-only state (jobs, chat, panels, constraints) never crosses over.
//
//   area/region  <-> aoi            base  <-> base            destination <-> destination
//   targets      ->  targets        selected route -> activeRoute + alternatives
//
// The dashboard "start" has no map counterpart and is not synced.
import { boundsToRegion, regionToBounds, toRouteResult, toScienceTarget } from '../api/mapping';
import type { BoundingBox, LonLat } from '../types/contracts';
import type { Pt, Region } from '../types/ui';
import { lonLatToPx, pxToLonLat } from '../utils/geo';
import { useStore as dash } from './dashboardStore';
import { useMissionStore as map } from './missionStore';

const EPS_PX = 0.01;
const EPS_DEG = 1e-9;

const samePt = (a?: Pt | null, b?: Pt | null) => (!a && !b) || (!!a && !!b && Math.hypot(a.x - b.x, a.y - b.y) < EPS_PX);
const sameLonLat = (a?: LonLat, b?: LonLat) =>
  (!a && !b) || (!!a && !!b && Math.abs(a.latitude_deg - b.latitude_deg) < EPS_DEG && Math.abs(a.longitude_deg_east - b.longitude_deg_east) < EPS_DEG);
const sameBounds = (a?: BoundingBox, b?: BoundingBox) =>
  (!a && !b) || (!!a && !!b && Math.abs(a.west_deg_east - b.west_deg_east) < EPS_DEG && Math.abs(a.east_deg_east - b.east_deg_east) < EPS_DEG &&
    Math.abs(a.south_deg - b.south_deg) < EPS_DEG && Math.abs(a.north_deg - b.north_deg) < EPS_DEG);

let busy = false;
/** Runs a sync step once; changes it causes in the other store are not echoed back. */
function once(fn: () => void) {
  if (busy) return;
  busy = true;
  try { fn(); } catch (e) { console.warn('[store bridge]', (e as Error).message); } finally { busy = false; }
}

export function pushDashboardToMap() {
  const d = dash.getState();
  const m = map.getState();
  const bounds = d.region ? regionToBounds(d.region) : undefined;
  if (!sameBounds(bounds, m.aoi)) map.getState().setAoi(bounds);        // clears region-derived map data, so it goes first
  const base = pxToLonLat(d.base);
  if (!sameLonLat(base, map.getState().base)) map.getState().setBase(base);
  const dest = d.dest ? pxToLonLat(d.dest) : undefined;
  if (!sameLonLat(dest, map.getState().destination)) map.getState().setDestination(dest);
  const targets = d.targets.map(toScienceTarget);
  const have = map.getState().targets;
  if (targets.length !== have.length || targets.some((t, i) => t.id !== have[i].id)) map.getState().setTargets(targets);
  const routes = d.mode === 'route' ? d.routes : [];
  const selected = routes[d.sel];
  const nextRoute = selected ? toRouteResult(selected, `route-${selected.k}`) : undefined;
  if (nextRoute?.id !== map.getState().activeRoute?.id) map.getState().setActiveRoute(nextRoute);
  const alternatives = routes.filter((_, i) => i !== d.sel).map((r) => toRouteResult(r, `route-${r.k}`));
  if (alternatives.map((a) => a.id).join() !== map.getState().alternatives.map((a) => a.id).join()) map.setState({ alternatives });
}

export function pushMapToDashboard() {
  const m = map.getState();
  const d = dash.getState();
  if (m.aoi) {
    const r: Region = boundsToRegion(m.aoi);
    if (!d.region || !samePt({ x: r.x, y: r.y }, { x: d.region.x, y: d.region.y }) || Math.abs(r.w - d.region.w) > EPS_PX || Math.abs(r.h - d.region.h) > EPS_PX) d.setRegion(r);
  }
  if (m.base) {
    const p = lonLatToPx(m.base);
    if (!samePt(p, d.base)) d.setField('base', p);
  }
  if (m.destination) {
    const p = lonLatToPx(m.destination);
    if (!samePt(p, d.dest)) d.setField('dest', { x: p.x, y: p.y });
  }
}

/** Starts two-way syncing and returns a function that stops it. Safe to call once at app start. */
export function startStoreBridge(): () => void {
  once(pushDashboardToMap);
  const stopDash = dash.subscribe((s, prev) => {
    if (s.region !== prev.region || s.base !== prev.base || s.dest !== prev.dest || s.targets !== prev.targets ||
      s.routes !== prev.routes || s.sel !== prev.sel || s.mode !== prev.mode) once(pushDashboardToMap);
  });
  const stopMap = map.subscribe((s, prev) => {
    if (s.aoi !== prev.aoi || s.base !== prev.base || s.destination !== prev.destination) once(pushMapToDashboard);
  });
  return () => { stopDash(); stopMap(); };
}
