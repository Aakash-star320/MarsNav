import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.connectors.ode.ode_rest import OdeError, build_product_query, parse_product_results, to_ode_longitude
from app.schemas import BoundingBox, CoverageStatus, DatasetCategory

FIXTURE = Path(__file__).parents[2] / "fixtures" / "ode" / "hirise_rdrv11_bbox_mpf.json"
PAYLOAD = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
AOI = BoundingBox(west_deg_east=1.0, south_deg=0.0, east_deg_east=5.0, north_deg=10.0)


def test_query_uses_documented_parameters_and_zero_360_longitude() -> None:
    url = build_product_query(AOI, ihid="MRO", iid="HiRISE", pt="RDRV11", limit=2)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert urlparse(url).netloc == "oderest.rsl.wustl.edu"
    assert q["loc"] == "b" and q["query"] == "products" and q["output"] == "JSON"
    assert (q["westernlon"], q["easternlon"], q["minlat"], q["maxlat"]) == ("1.0", "5.0", "0.0", "10.0")
    assert to_ode_longitude(-90.0) == 270.0


def test_query_rejects_aoi_that_wraps_in_ode_longitude() -> None:
    wraps = BoundingBox(west_deg_east=-10.0, south_deg=0.0, east_deg_east=10.0, north_deg=5.0)
    with pytest.raises(OdeError):
        build_product_query(wraps, ihid="MRO", iid="HiRISE", pt="RDRV11")


def test_parses_real_recorded_reply() -> None:
    recs = parse_product_results(PAYLOAD, category=DatasetCategory.imagery, aoi=AOI)
    assert len(recs) == 2
    r = recs[0]
    assert r.source == "ode" and r.product_id == "ESP_013057_1825_COLOR" and r.version == "1.0"
    fp = r.coverage.footprint
    assert (fp.west_deg_east, fp.east_deg_east) == (1.4001, 1.4412)
    assert (fp.south_deg, fp.north_deg) == (2.5226, 2.7062)
    assert r.coverage.status == CoverageStatus.partial and 0 < r.coverage.percent_of_aoi < 1
    assert str(r.download_url).endswith("ESP_013057_1825_COLOR.JP2")
    assert r.resolution_m_per_px is None               # Map_scale units are not documented
    assert any("Map_scale" in s for s in r.limitations)
    assert r.source_spatial_metadata.longitude_domain == "0-360"


def test_record_ids_are_stable() -> None:
    a = parse_product_results(PAYLOAD, category=DatasetCategory.imagery, aoi=AOI)
    b = parse_product_results(PAYLOAD, category=DatasetCategory.imagery, aoi=AOI)
    assert [x.id for x in a] == [x.id for x in b]


def test_failed_reply_is_an_error_not_empty_data() -> None:
    with pytest.raises(OdeError):
        parse_product_results({"ODEResults": {"Status": "Error"}}, category=DatasetCategory.imagery, aoi=AOI)


def test_records_without_ids_are_skipped_not_invented() -> None:
    payload = {"ODEResults": {"Status": "Success", "Products": {"Product": {"Footprint_geometry": "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))"}}}}
    assert parse_product_results(payload, category=DatasetCategory.imagery, aoi=AOI) == []


def test_meridian_crossing_footprint_is_flagged_unknown() -> None:
    payload = {"ODEResults": {"Status": "Success", "Products": {"Product": {
        "pdsid": "X", "Footprints_cross_meridian": "True", "Footprint_geometry": "POLYGON ((359 1, 1 1, 1 2, 359 2, 359 1))"}}}}
    rec = parse_product_results(payload, category=DatasetCategory.imagery, aoi=AOI)[0]
    assert rec.coverage.footprint is None and rec.coverage.status == CoverageStatus.unknown
    assert any("meridian" in s for s in rec.limitations)
