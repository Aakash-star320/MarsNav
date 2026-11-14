import { describe, it, expect } from "vitest";
import {
  normalizeLongitude,
  validatePoint,
  validateBounds,
  corners,
  project,
  unproject,
  validateDem,
  heightAt,
  gridXY,
  validateRoute,
  segmentHits,
  routeHits,
} from "../geometry";
import { demoDem, mission } from "../fixtures";
describe("canonical coordinates", () => {
  it.each([
    [180, -180],
    [350, -10],
    [-190, 170],
    [720, 0],
  ])("normalizes %s", (a, b) => expect(normalizeLongitude(a)).toBe(b));
  it.each([NaN, Infinity, -Infinity])("rejects nonfinite longitude", (v) =>
    expect(() => normalizeLongitude(v)).toThrow(),
  );
  it.each([-91, 91, NaN, Infinity])("rejects latitude", (v) =>
    expect(() =>
      validatePoint({ latitude_deg: v, longitude_deg_east: 0 }),
    ).toThrow(),
  );
  it("rejects longitude 180", () =>
    expect(() =>
      validatePoint({ latitude_deg: 0, longitude_deg_east: 180 }),
    ).toThrow());
  it("roundtrips local metres", () => {
    const p = unproject(300, -400, demoDem.projection);
    const xy = project(p, demoDem.projection);
    expect(xy[0]).toBeCloseTo(300, 5);
    expect(xy[1]).toBeCloseTo(-400, 5);
  });
  it("reverses corner order", () =>
    expect(corners(mission.base, mission.destination)).toEqual(
      corners(mission.destination, mission.base),
    ));
  it("rejects degenerate AOI", () =>
    expect(() => corners(mission.base, mission.base)).toThrow());
  it("rejects seam selection", () =>
    expect(() =>
      corners(
        { latitude_deg: 0, longitude_deg_east: 179 },
        { latitude_deg: 1, longitude_deg_east: -179 },
      ),
    ).toThrow());
  it("rejects inverted bounds", () =>
    expect(() =>
      validateBounds({
        ...mission.bounds,
        north_deg: mission.bounds.south_deg,
      }),
    ).toThrow());
});
describe("DEM metadata and no-data", () => {
  it("accepts the generated fixture", () =>
    expect(() => validateDem(demoDem)).not.toThrow());
  it("rejects wrong sample count", () =>
    expect(() => validateDem({ ...demoDem, values: [] })).toThrow());
  it("rejects unsupported projection", () =>
    expect(() =>
      validateDem({
        ...demoDem,
        projection: { ...demoDem.projection, kind: "earth" as any },
      }),
    ).toThrow());
  it("rejects singular affine", () =>
    expect(() =>
      validateDem({ ...demoDem, affine: [0, 0, 0, 0, 0, 0] }),
    ).toThrow());
  it("rejects nonfinite heights", () =>
    expect(() =>
      validateDem({
        ...demoDem,
        values: demoDem.values.map((v, i) => (i === 10 ? NaN : v)),
      }),
    ).toThrow());
  it("rejects entirely missing elevation", () =>
    expect(() =>
      validateDem({ ...demoDem, values: demoDem.values.map(() => null) }),
    ).toThrow());
  it("uses affine row direction", () =>
    expect(gridXY(demoDem, 1, 1)).toEqual([-1175, 1175]));
  it("retains missing northeast samples", () =>
    expect(
      heightAt(demoDem, unproject(1100, 1100, demoDem.projection)),
    ).toBeNull());
  it("returns null outside coverage", () =>
    expect(
      heightAt(demoDem, unproject(2000, 0, demoDem.projection)),
    ).toBeNull());
  it("samples valid terrain", () =>
    expect(heightAt(demoDem, mission.base)).not.toBeNull());
});
describe("route and blocked geometry", () => {
  it("accepts fixture route", () =>
    expect(() => validateRoute(mission.route)).not.toThrow());
  it("rejects one-point route", () =>
    expect(() =>
      validateRoute({ ...mission.route, geometry: [mission.base] }),
    ).toThrow());
  it("permits no route response", () =>
    expect(() =>
      validateRoute({ ...mission.route, feasible: false, geometry: [] }),
    ).not.toThrow());
  const box = {
    west_deg_east: 0,
    east_deg_east: 1,
    south_deg: 0,
    north_deg: 1,
  };
  it("detects crossing even with endpoints outside", () =>
    expect(
      segmentHits(
        { latitude_deg: 0.5, longitude_deg_east: -1 },
        { latitude_deg: 0.5, longitude_deg_east: 2 },
        box,
      ),
    ).toBe(true));
  it("rejects parallel outside segment", () =>
    expect(
      segmentHits(
        { latitude_deg: 2, longitude_deg_east: -1 },
        { latitude_deg: 2, longitude_deg_east: 2 },
        box,
      ),
    ).toBe(false));
  it("detects boundary touch", () =>
    expect(
      segmentHits(
        { latitude_deg: 0, longitude_deg_east: -1 },
        { latitude_deg: 0, longitude_deg_east: 0 },
        box,
      ),
    ).toBe(true));
  it("detects zero-length point inside", () =>
    expect(
      segmentHits(
        { latitude_deg: 0.5, longitude_deg_east: 0.5 },
        { latitude_deg: 0.5, longitude_deg_east: 0.5 },
        box,
      ),
    ).toBe(true));
  it("has no intersection without blocks", () =>
    expect(routeHits(mission.route, [])).toBe(false));
});
