import { describe, expect, it } from 'vitest';
import { boundsToRegion, fromScienceTarget, regionToBounds, toScienceTarget } from './mapping';

describe('contract mapping', () => {
  it('round-trips a region through BoundingBox', () => {
    const r = { x: 20, y: 20, w: 760, h: 460 }, back = boundsToRegion(regionToBounds(r));
    for (const k of ['x', 'y', 'w', 'h'] as const) expect(back[k]).toBeCloseTo(r[k], 6);
  });
  it('produces a valid east-positive bounding box', () => {
    const b = regionToBounds({ x: 20, y: 20, w: 760, h: 460 });
    expect(b.east_deg_east).toBeGreaterThan(b.west_deg_east);
    expect(b.north_deg).toBeGreaterThan(b.south_deg);
  });
  it('round-trips a science target', () => {
    const t = { id: 'T-01', cat: 'Layered outcrop', x: 100, y: 200, score: 80, conf: 'Medium' };
    const s = toScienceTarget(t), back = fromScienceTarget(s);
    expect(s.confidence).toBe('medium');
    expect(back.x).toBeCloseTo(100, 6); expect(back.conf).toBe('Medium');
  });
});
