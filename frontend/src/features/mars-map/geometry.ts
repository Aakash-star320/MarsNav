import type {
  BoundingBox,
  LonLat,
  RouteResult,
  BlockedArea,
} from "../../types/contracts";
import type { Dem, Projection } from "./types";
export const normalizeLongitude = (x: number) => {
  if (!Number.isFinite(x)) throw Error("Longitude must be finite");
  return ((((x + 180) % 360) + 360) % 360) - 180;
};
export function validatePoint(p: LonLat) {
  if (
    !Number.isFinite(p.latitude_deg) ||
    Math.abs(p.latitude_deg) > 90 ||
    !Number.isFinite(p.longitude_deg_east) ||
    p.longitude_deg_east < -180 ||
    p.longitude_deg_east >= 180
  )
    throw Error("Invalid canonical Mars coordinate");
}
export function validateBounds(b: BoundingBox) {
  validatePoint({
    latitude_deg: b.south_deg,
    longitude_deg_east: b.west_deg_east,
  });
  validatePoint({
    latitude_deg: b.north_deg,
    longitude_deg_east: b.east_deg_east,
  });
  if (b.south_deg >= b.north_deg || b.west_deg_east >= b.east_deg_east)
    throw Error(
      "Bounds must have positive area and cannot cross the antimeridian",
    );
}
export function corners(a: LonLat, b: LonLat): BoundingBox {
  validatePoint(a);
  validatePoint(b);
  if (Math.abs(a.longitude_deg_east - b.longitude_deg_east) > 180)
    throw Error("Antimeridian crossing is unsupported");
  const r = {
    west_deg_east: Math.min(a.longitude_deg_east, b.longitude_deg_east),
    east_deg_east: Math.max(a.longitude_deg_east, b.longitude_deg_east),
    south_deg: Math.min(a.latitude_deg, b.latitude_deg),
    north_deg: Math.max(a.latitude_deg, b.latitude_deg),
  };
  validateBounds(r);
  return r;
}
export const latLng = (p: LonLat): [number, number] => {
  validatePoint(p);
  return [p.latitude_deg, p.longitude_deg_east];
};
export const label = (p?: LonLat) =>
  p
    ? `${Math.abs(p.latitude_deg).toFixed(5)}° ${p.latitude_deg < 0 ? "S" : "N"} / ${Math.abs(p.longitude_deg_east).toFixed(5)}° ${p.longitude_deg_east < 0 ? "W" : "E"}`
    : "Not selected";
export function project(p: LonLat, q: Projection): [number, number] {
  validatePoint(p);
  const k = (q.radius_m * Math.PI) / 180;
  return [
    (p.longitude_deg_east - q.longitude_origin_deg_east) *
      k *
      Math.cos((q.latitude_origin_deg * Math.PI) / 180),
    (p.latitude_deg - q.latitude_origin_deg) * k,
  ];
}
export function unproject(x: number, y: number, q: Projection): LonLat {
  const k = (q.radius_m * Math.PI) / 180;
  const p = {
    latitude_deg: q.latitude_origin_deg + y / k,
    longitude_deg_east:
      q.longitude_origin_deg_east +
      x / (k * Math.cos((q.latitude_origin_deg * Math.PI) / 180)),
  };
  validatePoint(p);
  return p;
}
export function validateDem(d: Dem) {
  if (
    d.version !== 1 ||
    d.projection?.kind !== "mars-local-equirectangular" ||
    d.sample_registration !== "point" ||
    d.units !== "m" ||
    !d.vertical_datum
  )
    throw Error("Unsupported DEM projection, registration or units");
  validateBounds(d.bounds);
  if (
    !Number.isFinite(d.projection.radius_m) ||
    d.projection.radius_m <= 0 ||
    !Number.isFinite(d.projection.latitude_origin_deg) ||
    Math.abs(d.projection.latitude_origin_deg) >= 90 ||
    !Number.isFinite(d.projection.longitude_origin_deg_east)
  )
    throw Error("Invalid Mars projection parameters");
  if (
    !Number.isInteger(d.width) ||
    !Number.isInteger(d.height) ||
    d.width < 2 ||
    d.height < 2 ||
    d.width * d.height > 1000000 ||
    d.values.length !== d.width * d.height
  )
    throw Error("Invalid DEM dimensions");
  if (
    d.affine.length !== 6 ||
    !d.affine.every(Number.isFinite) ||
    Math.abs(d.affine[1] * d.affine[5] - d.affine[2] * d.affine[4]) < 1e-9
  )
    throw Error("Invalid DEM affine transform");
  if (
    d.values.some((v) => v !== null && !Number.isFinite(v)) ||
    d.values.every((v) => v === null)
  )
    throw Error("DEM has invalid or no elevation samples");
}
export function gridXY(d: Dem, c: number, r: number): [number, number] {
  const a = d.affine;
  return [a[0] + c * a[1] + r * a[2], a[3] + c * a[4] + r * a[5]];
}
export function heightAt(d: Dem, p: LonLat): number | null {
  const [x, y] = project(p, d.projection),
    a = d.affine,
    det = a[1] * a[5] - a[2] * a[4],
    dx = x - a[0],
    dy = y - a[3];
  let c = (dx * a[5] - dy * a[2]) / det,
    r = (dy * a[1] - dx * a[4]) / det;
  if (
    c < -1e-7 ||
    r < -1e-7 ||
    c > d.width - 1 + 1e-7 ||
    r > d.height - 1 + 1e-7
  )
    return null;
  c = Math.max(0, Math.min(d.width - 1, c));
  r = Math.max(0, Math.min(d.height - 1, r));
  const c0 = Math.min(Math.floor(c), d.width - 2),
    r0 = Math.min(Math.floor(r), d.height - 2),
    u = c - c0,
    v = r - r0;
  const z = [
    d.values[r0 * d.width + c0],
    d.values[r0 * d.width + c0 + 1],
    d.values[(r0 + 1) * d.width + c0],
    d.values[(r0 + 1) * d.width + c0 + 1],
  ];
  if (z.some((t) => t === null)) return null;
  return (
    z[0]! * (1 - u) * (1 - v) +
    z[1]! * u * (1 - v) +
    z[2]! * (1 - u) * v +
    z[3]! * u * v
  );
}
export function validateRoute(r: RouteResult) {
  if (!r.feasible) return;
  if (r.geometry.length < 2) throw Error("Route needs at least two points");
  r.geometry.forEach(validatePoint);
  r.waypoints.forEach(validatePoint);
  r.geometry.slice(1).forEach((p, i) => {
    if (Math.abs(p.longitude_deg_east - r.geometry[i].longitude_deg_east) > 180)
      throw Error("Antimeridian route unsupported");
  });
}
export function segmentHits(a: LonLat, b: LonLat, r: BoundingBox) {
  let lo = 0,
    hi = 1;
  const dx = b.longitude_deg_east - a.longitude_deg_east,
    dy = b.latitude_deg - a.latitude_deg;
  const ps = [-dx, dx, -dy, dy],
    qs = [
      a.longitude_deg_east - r.west_deg_east,
      r.east_deg_east - a.longitude_deg_east,
      a.latitude_deg - r.south_deg,
      r.north_deg - a.latitude_deg,
    ];
  for (let i = 0; i < 4; i++) {
    if (ps[i] === 0) {
      if (qs[i] < 0) return false;
    } else {
      const t = qs[i] / ps[i];
      if (ps[i] < 0) lo = Math.max(lo, t);
      else hi = Math.min(hi, t);
      if (lo > hi) return false;
    }
  }
  return true;
}
export const routeHits = (r: RouteResult, blocks: BlockedArea[]) =>
  r.geometry
    .slice(1)
    .some((p, i) =>
      blocks.some((b) => segmentHits(r.geometry[i], p, b.bounds)),
    );
