import { describe, expect, it } from "vitest";
import {
  TREK_MAX_LEVEL,
  trekLevelFor,
  trekPxPerDeg,
  trekTilesFor,
  trekUrl,
} from "../BaseImagery";

describe("Mars Trek tile math", () => {
  it("finds the tile that was fetched live for Jezero (zoom 7, row 50, col 183)", () => {
    const t = trekTilesFor(7, 77.4, 18.4, 77.4001, 18.4001);
    expect(t).toHaveLength(1);
    expect([t[0].level, t[0].row, t[0].col]).toEqual([7, 50, 183]);
    expect(trekUrl(t[0])).toBe(
      "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/7/50/183.jpg",
    );
  });

  it("tile edges are consistent with the grid (top-left -180, 90; 180 / 2^z degrees)", () => {
    const [t] = trekTilesFor(7, 77.4, 18.4, 77.4001, 18.4001);
    expect(t.east - t.west).toBeCloseTo(180 / 128, 12);
    expect(t.west).toBeLessThanOrEqual(77.4);
    expect(t.east).toBeGreaterThan(77.4);
    expect(t.north).toBeGreaterThan(18.4);
    expect(t.south).toBeLessThanOrEqual(18.4);
  });

  it("covers the whole globe with 2 x 1 tiles at level 0", () => {
    const all = trekTilesFor(0, -180, -90, 180, 90);
    expect(all.map((t) => [t.row, t.col])).toEqual([[0, 0], [0, 1]]);
  });

  it("returns every tile a box spans, and none outside the planet", () => {
    const span = trekTilesFor(7, 77.0, 18.0, 78.5, 19.5);
    expect(span.length).toBe(new Set(span.map((t) => t.col)).size * new Set(span.map((t) => t.row)).size);
    expect(trekTilesFor(3, 190, 0, 200, 10)).toEqual([]);
    expect(trekTilesFor(3, -200, 0, -180, 10)).toEqual([]);
    expect(trekTilesFor(3, 10, 95, 20, 100)).toEqual([]);
  });

  it("picks the coarsest level that is still sharp enough, capped at the service maximum", () => {
    expect(trekLevelFor(trekPxPerDeg(3))).toBe(3);
    expect(trekLevelFor(trekPxPerDeg(3) * 1.01)).toBe(4);
    expect(trekLevelFor(1e9)).toBe(TREK_MAX_LEVEL);
    expect(trekLevelFor(0.0001)).toBe(0);
  });
});
