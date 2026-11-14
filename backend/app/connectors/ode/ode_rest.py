"""ODE REST (https://oderest.rsl.wustl.edu/) request builder and product-metadata parser.

Verified against the ODE REST V2.1.6 manual and recorded live replies
(``backend/tests/fixtures/ode``). Facts relied on:

* Bounding-box queries use ``minlat``, ``maxlat``, ``westernlon``, ``easternlon`` and ``loc=b``.
  ODE longitudes are positive east, 0-360. This module converts to and from the canonical
  [-180, 180) convention at the boundary.
* ``results=m`` returns product metadata, ``p`` returns PDS identifiers (``pdsid``), ``f`` returns
  product files, ``c`` returns only a count. ``limit`` and ``offset`` page through results.
* Footprints are WKT polygons in 0-360 east longitude. The shared contract carries a bounding box
  footprint only, so the exact polygon is reduced to its bounds and that is stated in
  ``limitations``.
* ``Map_scale`` units are not documented in the manual, so no resolution is derived from it; the
  raw value is preserved in ``limitations``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid5

from app.schemas import (
    BoundingBox,
    CoverageStatus,
    DatasetCategory,
    DatasetCoverage,
    DatasetRecord,
    FreshnessState,
    SourceSpatialMetadata,
)

from app.analyzer.discovery.mars_geometry import bounds_area_m2, intersect_bounds, wrap_longitude_deg

DEFAULT_BASE_URL = "https://oderest.rsl.wustl.edu/live2"


class OdeError(ValueError):
    """The reply was not a successful, parseable ODE result."""


def to_ode_longitude(lon_deg_east: float) -> float:
    """Canonical [-180, 180) east longitude -> ODE positive-east 0-360."""
    return lon_deg_east % 360.0


def build_product_query(
    aoi: BoundingBox, *, ihid: str, iid: str, pt: str, results: str = "mp", limit: int = 25, offset: int = 0,
    base_url: str = DEFAULT_BASE_URL, target: str = "mars",
) -> str:
    """URL for a bounding-box product search (``loc=b``: product bounding box intersects the AOI)."""
    west, east = to_ode_longitude(aoi.west_deg_east), to_ode_longitude(aoi.east_deg_east)
    if west >= east:
        raise OdeError("AOI crosses the 0/360 seam in ODE longitude; split it before querying")
    params = {
        "query": "products", "target": target, "results": results, "ihid": ihid, "iid": iid, "pt": pt,
        "minlat": aoi.south_deg, "maxlat": aoi.north_deg, "westernlon": west, "easternlon": east, "loc": "b",
        "limit": limit, "offset": offset, "output": "JSON",
    }
    return f"{base_url}?{urlencode(params)}"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _polygon_bounds(wkt: str | None) -> tuple[float, float, float, float] | None:
    """(west, south, east, north) of a WKT POLYGON/MULTIPOLYGON, or None when empty/unparseable."""
    if not wkt or "EMPTY" in wkt.upper():
        return None
    pairs = re.findall(r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", wkt)
    if not pairs:
        return None
    lons = [float(a) for a, _ in pairs]
    lats = [float(b) for _, b in pairs]
    return min(lons), min(lats), max(lons), max(lats)


def _footprint_bbox(product: dict[str, Any]) -> tuple[BoundingBox | None, str | None]:
    """Canonical footprint bounds, or (None, reason) when it cannot be represented."""
    if str(product.get("Footprints_cross_meridian", "")).lower() == "true":
        return None, "footprint crosses the 0/360 meridian and cannot be represented as one bounding box"
    b = _polygon_bounds(product.get("Footprint_geometry"))
    if b is None:
        try:
            b = (float(product["Westernmost_longitude"]), float(product["Minimum_latitude"]),
                 float(product["Easternmost_longitude"]), float(product["Maximum_latitude"]))
        except (KeyError, TypeError, ValueError):
            return None, "no usable footprint in the ODE record"
    west, south, east, north = b
    west_c, east_c = wrap_longitude_deg(west), wrap_longitude_deg(east)
    if not (west_c < east_c and south < north):
        return None, "footprint bounds are degenerate or cross the antimeridian"
    return BoundingBox(west_deg_east=west_c, south_deg=south, east_deg_east=east_c, north_deg=north), None


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_product_results(payload: dict[str, Any], *, category: DatasetCategory, aoi: BoundingBox) -> list[DatasetRecord]:
    """Normalize an ODE JSON reply into DatasetRecords.

    ``category`` comes from the caller's query (instrument/product type), never guessed from the
    record. Records without a product id are skipped rather than given invented ids.
    """
    root = payload.get("ODEResults")
    if not isinstance(root, dict) or root.get("Status") != "Success":
        raise OdeError(f"ODE reply was not successful: {root.get('Status') if isinstance(root, dict) else 'missing ODEResults'}")
    products = _as_list((root.get("Products") or {}).get("Product"))
    records: list[DatasetRecord] = []
    for p in products:
        product_id = p.get("pdsid")
        if not product_id:
            continue
        footprint, reason = _footprint_bbox(p)
        limitations = ["Footprint reduced to its bounding box; the exact ODE polygon is not carried in the shared contract."]
        if reason:
            limitations.append(reason)
        if p.get("Map_scale") is not None:
            limitations.append(f"ODE Map_scale={p['Map_scale']} (units not documented in the ODE manual; no resolution derived).")
        overlap = intersect_bounds(footprint, aoi) if footprint else None
        percent = 100.0 * bounds_area_m2(overlap) / bounds_area_m2(aoi) if overlap else 0.0
        status = (CoverageStatus.available if percent >= 99.5 else CoverageStatus.partial) if overlap else (
            CoverageStatus.unavailable if footprint else CoverageStatus.unknown)
        files = [f for f in _as_list((p.get("Product_files") or {}).get("Product_file")) if f.get("Type") == "Product"]
        records.append(DatasetRecord(
            id=uuid5(NAMESPACE_URL, f"ode:{product_id}:{p.get('Product_version_id') or ''}"),
            source="ode", product_id=product_id, version=p.get("Product_version_id"),
            category=category,
            coverage=DatasetCoverage(status=status, percent_of_aoi=round(min(percent, 100.0), 4), footprint=footprint),
            freshness=FreshnessState.unable_to_verify,
            acquired_at=_parse_time(p.get("UTC_start_time")),
            download_url=files[0].get("URL") if files else None,
            provenance_url=p.get("ProductURL"),
            source_spatial_metadata=SourceSpatialMetadata(
                latitude_type="planetocentric", longitude_direction="east", longitude_domain="0-360",
                body_name="Mars",
            ),
            limitations=limitations,
        ))
    return records
