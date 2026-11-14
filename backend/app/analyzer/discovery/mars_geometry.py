"""Mars planetary geometry helpers.

Spherical approximation with the documented mean radius (3389.5 km); never Earth defaults.
Coordinates are planetocentric latitude and east-positive longitude in [-180, 180).
Local metric offsets use an equirectangular frame about an origin: x east, y north, in metres.
"""
from __future__ import annotations

import math

from app.schemas import BoundingBox, LonLat

MARS_MEAN_RADIUS_M = 3_389_500.0
METRES_PER_DEG_LAT = math.pi / 180.0 * MARS_MEAN_RADIUS_M
MAX_USABLE_ABS_LAT_DEG = 89.0


class GeometryError(ValueError):
    """Raised when a request cannot be represented in the canonical coordinate convention."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def wrap_longitude_deg(lon: float) -> float:
    """Normalize any east-positive longitude to [-180, 180)."""
    if -180.0 <= lon < 180.0:
        return lon  # already canonical: avoid modulo rounding noise
    return ((lon + 180.0) % 360.0) - 180.0


def haversine_m(a: LonLat, b: LonLat) -> float:
    p1, p2 = math.radians(a.latitude_deg), math.radians(b.latitude_deg)
    dphi = p2 - p1
    dlmb = math.radians(wrap_longitude_deg(b.longitude_deg_east - a.longitude_deg_east))
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * MARS_MEAN_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def to_local_xy_m(origin: LonLat, p: LonLat) -> tuple[float, float]:
    """Metric east/north offset of p from origin (equirectangular about the origin latitude)."""
    dlon = wrap_longitude_deg(p.longitude_deg_east - origin.longitude_deg_east)
    x = math.radians(dlon) * MARS_MEAN_RADIUS_M * math.cos(math.radians(origin.latitude_deg))
    y = (p.latitude_deg - origin.latitude_deg) * METRES_PER_DEG_LAT
    return x, y


def from_local_xy_m(origin: LonLat, x: float, y: float) -> LonLat:
    lat = origin.latitude_deg + y / METRES_PER_DEG_LAT
    if abs(lat) > 90:
        raise GeometryError("outside_planet", "offset leaves the planet's latitude range")
    cos_lat = math.cos(math.radians(origin.latitude_deg))
    if cos_lat < 1e-6:
        raise GeometryError("polar_origin", "local frame is degenerate at the poles")
    lon = origin.longitude_deg_east + math.degrees(x / (MARS_MEAN_RADIUS_M * cos_lat))
    return LonLat(latitude_deg=lat, longitude_deg_east=wrap_longitude_deg(lon))


def bounds_from_local_extents(origin: LonLat, min_x: float, max_x: float, min_y: float, max_y: float) -> BoundingBox:
    """Canonical BoundingBox enclosing a metric rectangle about origin.

    Rejects antimeridian crossings and polar regions rather than producing an invalid or
    misleading box. Longitude offsets use the origin-latitude scale, which matches
    ``to_local_xy_m`` so points round-trip into the box.
    """
    south = origin.latitude_deg + min_y / METRES_PER_DEG_LAT
    north = origin.latitude_deg + max_y / METRES_PER_DEG_LAT
    if south < -MAX_USABLE_ABS_LAT_DEG or north > MAX_USABLE_ABS_LAT_DEG:
        raise GeometryError("polar_region", "region reaches latitudes too close to a pole for a local frame")
    cos_origin = math.cos(math.radians(origin.latitude_deg))
    west = origin.longitude_deg_east + math.degrees(min_x / (MARS_MEAN_RADIUS_M * cos_origin))
    east = origin.longitude_deg_east + math.degrees(max_x / (MARS_MEAN_RADIUS_M * cos_origin))
    if west < -180.0 or east >= 180.0:
        raise GeometryError("antimeridian", "region crosses the antimeridian; split it into two AOIs")
    return BoundingBox(west_deg_east=west, south_deg=south, east_deg_east=east, north_deg=north)


def bounds_area_m2(b: BoundingBox) -> float:
    lat_mid = math.radians((b.north_deg + b.south_deg) / 2)
    width = math.radians(b.east_deg_east - b.west_deg_east) * MARS_MEAN_RADIUS_M * math.cos(lat_mid)
    height = (b.north_deg - b.south_deg) * METRES_PER_DEG_LAT
    return width * height


def intersect_bounds(a: BoundingBox, b: BoundingBox) -> BoundingBox | None:
    west, east = max(a.west_deg_east, b.west_deg_east), min(a.east_deg_east, b.east_deg_east)
    south, north = max(a.south_deg, b.south_deg), min(a.north_deg, b.north_deg)
    if east <= west or north <= south:
        return None
    return BoundingBox(west_deg_east=west, south_deg=south, east_deg_east=east, north_deg=north)


def pad_bounds(b: BoundingBox, margin_m: float) -> BoundingBox:
    """Grow a box by a metric margin on every side; rejects results the canonical box cannot hold."""
    if margin_m <= 0:
        return b
    south, north = b.south_deg - margin_m / METRES_PER_DEG_LAT, b.north_deg + margin_m / METRES_PER_DEG_LAT
    if south < -MAX_USABLE_ABS_LAT_DEG or north > MAX_USABLE_ABS_LAT_DEG:
        raise GeometryError("polar_region", "padded region reaches latitudes too close to a pole")
    cos_edge = math.cos(math.radians(max(abs(south), abs(north))))
    dlon = math.degrees(margin_m / (MARS_MEAN_RADIUS_M * cos_edge))
    west, east = b.west_deg_east - dlon, b.east_deg_east + dlon
    if west < -180.0 or east >= 180.0:
        raise GeometryError("antimeridian", "padded region crosses the antimeridian; split it into two AOIs")
    return BoundingBox(west_deg_east=west, south_deg=south, east_deg_east=east, north_deg=north)
