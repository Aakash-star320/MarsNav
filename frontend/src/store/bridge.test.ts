import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { lonLatToPx, pxToLonLat } from '../utils/geo';
import { startStoreBridge } from './bridge';
import { useStore as dash } from './dashboardStore';
import { useMissionStore as map } from './missionStore';

let stop: () => void;
beforeEach(() => {
  dash.getState().reset();
  map.getState().reset();
  stop = startStoreBridge();
});
afterEach(() => stop());

describe('store bridge', () => {
  it('pushes the dashboard base to the map store at start', () => {
    const b = map.getState().base!;
    expect(lonLatToPx(b).x).toBeCloseTo(dash.getState().base.x, 6);
  });

  it('turns a dashboard region into a map AOI with canonical bounds', () => {
    dash.getState().setRegion({ x: 100, y: 100, w: 200, h: 100 });
    const aoi = map.getState().aoi!;
    expect(aoi.east_deg_east).toBeGreaterThan(aoi.west_deg_east);
    expect(aoi.north_deg).toBeGreaterThan(aoi.south_deg);
    expect(aoi.west_deg_east).toBeCloseTo(77.4 + 100 * 0.01, 9);
  });

  it('keeps the base and destination after the AOI changes (the AOI clears region data)', () => {
    dash.getState().setField('dest', { x: 300, y: 200 });
    dash.getState().setRegion({ x: 50, y: 50, w: 400, h: 300 });
    expect(map.getState().destination).toBeDefined();
    expect(map.getState().base).toBeDefined();
  });

  it('copies a base picked on the map back to the dashboard', () => {
    map.getState().setBase(pxToLonLat({ x: 222, y: 111 }));
    expect(dash.getState().base.x).toBeCloseTo(222, 6);
    expect(dash.getState().base.y).toBeCloseTo(111, 6);
  });

  it('copies a destination and an AOI picked on the map back to the dashboard', () => {
    map.getState().setDestination(pxToLonLat({ x: 400, y: 150 }));
    expect(dash.getState().dest?.x).toBeCloseTo(400, 6);
    map.getState().setAoi({ west_deg_east: 78.0, south_deg: 15.0, east_deg_east: 80.0, north_deg: 17.0 });
    const r = dash.getState().region!;
    expect(r.w).toBeCloseTo(200, 6);
    expect(r.h).toBeCloseTo(200, 6);
  });

  it('does not loop or reset unrelated state when values are unchanged', () => {
    dash.getState().setField('slope', 9);
    dash.getState().setField('base', { ...dash.getState().base });
    expect(dash.getState().slope).toBe(9);
  });

  it('shares generated targets and the selected route with the map as contract types', () => {
    dash.getState().setRegion({ x: 20, y: 20, w: 760, h: 460 });
    dash.getState().analyze();
    // the mock analysis runs as a job; fill the state directly the way the job does when it finishes
    const targets = [{ id: 'T-01', cat: 'Layered outcrop', x: 200, y: 200, score: 80, conf: 'Medium' }];
    dash.setState({ targets });
    expect(map.getState().targets.map((t) => t.id)).toEqual(['T-01']);
    expect(map.getState().targets[0].location.latitude_deg).toBeCloseTo(18.4 - 200 * 0.01, 9);
  });

  it('stops syncing after the bridge is stopped', () => {
    stop();
    dash.getState().setRegion({ x: 10, y: 10, w: 100, h: 100 });
    expect(map.getState().aoi).toBeUndefined();
    stop = startStoreBridge();
  });
});
