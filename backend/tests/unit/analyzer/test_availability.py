from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.discovery.availability import CATALOG, AreaTooLarge, check_availability, match_entries
from app.api.routes import availability
from app.connectors.common.http import HttpFetchError
from app.schemas import BoundingBox

AOI = BoundingBox(west_deg_east=77.3, south_deg=18.2, east_deg_east=77.65, north_deg=18.5)


def product(pid, west, south, east, north):
    """One ODE product; ODE footprints use 0-360 east longitude."""
    ring = f"{west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}"
    return {"pdsid": pid, "Footprint_geometry": f"POLYGON (({ring}))", "ProductURL": f"https://ode.example/{pid}"}


def payload(*products):
    return {"ODEResults": {"Status": "Success", "Products": {"Product": list(products)} if products else {}}}


FULL = product("FULL_COVER", 77.0, 18.0, 78.0, 19.0)
HALF = product("HALF_COVER", 77.0, 18.0, 77.475, 19.0)           # the western half of the box


def catalog(by_iid, calls=None):
    """A fake ODE: answers by instrument id; an exception value is raised, a dict is returned."""
    def fetch(url):
        q = parse_qs(urlparse(url).query)
        iid = q["iid"][0]
        if calls is not None:
            calls.append((q["ihid"][0], iid, q["pt"][0], q["limit"][0]))
        out = by_iid.get(iid, payload())
        if isinstance(out, Exception):
            raise out
        return out
    return fetch


def test_the_catalog_is_unique_and_marks_only_what_this_tool_can_analyse() -> None:
    assert len({(e.ihid, e.iid, e.pt) for e in CATALOG}) == len(CATALOG) >= 8
    assert {e.instrument for e in CATALOG if e.analyzable} == {"CRISM", "MOLA"}


def test_supported_objective_with_coverage_says_so_with_the_percentage() -> None:
    calls = []
    res = check_availability("find hydrated minerals", AOI, fetch_json=catalog({"CRISM": payload(FULL)}, calls))
    assert res.supported and res.matched_objective_id == "hydrated_minerals"
    assert res.message.startswith("This objective is supported and NASA data covers 100% of the area")
    item = next(c for c in res.coverage if c.instrument == "CRISM")
    assert item.analyzable and item.covered_percent == pytest.approx(100.0, abs=1.0) and item.product_count == 1 and item.example_product_ids == ["FULL_COVER"]
    assert ("MRO", "CRISM", "MTRDR", "25") in calls                      # real ODE codes, limited to 25 products


def test_partial_coverage_is_the_union_of_the_footprints() -> None:
    res = check_availability("mineral composition", AOI, fetch_json=catalog({"CRISM": payload(HALF)}))
    item = next(c for c in res.coverage if c.instrument == "CRISM")
    assert 40 <= item.covered_percent <= 60
    union = check_availability("mineral composition", AOI, fetch_json=catalog({"CRISM": payload(HALF, product("EAST", 77.4, 18.0, 78.0, 19.0))}))
    assert next(c for c in union.coverage if c.instrument == "CRISM").covered_percent == pytest.approx(100.0, abs=1.0)


def test_data_that_exists_but_cannot_be_analysed_is_described_not_oversold() -> None:
    res = check_availability("map the boxwork formations", AOI, fetch_json=catalog({"HIRISE": payload(FULL)}))
    assert not res.supported and res.matched_objective_id is None
    assert "no method to extract it yet" in res.message and "cannot plan for this objective" in res.message
    hirise = [c for c in res.coverage if c.instrument.startswith("HiRISE") and c.product_count]
    assert hirise and all(not c.analyzable and "has no method to extract 'map the boxwork formations'" in c.note for c in hirise)


def test_no_products_means_a_plain_refusal_naming_the_instrument() -> None:
    res = check_availability("surface temperature at night", AOI, fetch_json=catalog({}))
    assert not res.supported
    assert "lists no THEMIS" in res.message and "cannot plan for this objective here" in res.message
    assert all(c.product_count == 0 and c.covered_percent == 0.0 for c in res.coverage)


def test_a_supported_objective_without_its_data_is_refused_for_this_area() -> None:
    res = check_availability("hydrated minerals", AOI, fetch_json=catalog({}))
    assert res.supported and "supported, but NASA's catalog lists no CRISM products" in res.message


def test_an_unreachable_catalog_never_becomes_a_claim_of_absence() -> None:
    down = HttpFetchError("unreachable", "no route to host")
    res = check_availability("hydrated minerals on flat terrain", AOI, fetch_json=catalog({"CRISM": down, "MOLA": down}))
    assert res.coverage == [] and res.message.startswith("I could not reach NASA's catalog, so I cannot tell whether data exists")
    assert "lists no" not in res.message and res.warnings
    mixed = check_availability("hydrated minerals on flat terrain", AOI, fetch_json=catalog({"CRISM": payload(FULL), "MOLA": down}))
    assert "covers 100%" in mixed.message and "could not check MOLA" in mixed.message and "may still exist" in mixed.message


def test_an_unusable_catalog_reply_counts_as_unreachable() -> None:
    res = check_availability("hydrated minerals", AOI, fetch_json=catalog({"CRISM": {"ODEResults": {"Status": "ERROR"}}, "MOLA": {"oops": 1}}))
    assert res.coverage == [] and "could not reach" in res.message


def test_an_objective_nobody_measures_is_declined_without_a_query() -> None:
    calls = []
    res = check_availability("find the best pizza", AOI, fetch_json=catalog({}, calls))
    assert not res.supported and res.coverage == [] and calls == []
    assert res.message == "I don't know which NASA instrument measures that, so I cannot check whether data exists."


def test_matching_prefers_the_instruments_the_words_point_to() -> None:
    assert [e.instrument for e in match_entries("thermal inertia of sand", None)][:1] == ["TES thermal inertia"]
    assert "SHARAD radar" in [e.instrument for e in match_entries("buried ice layers", None)]
    assert [e.instrument for e in match_entries("xyzzy", "hydrated_minerals")] == ["CRISM"]      # a supported objective brings its own data
    assert [e.instrument for e in match_entries("xyzzy", "flat_safe_sites")] == ["MOLA"]


def test_an_oversized_box_is_refused() -> None:
    big = BoundingBox(west_deg_east=70.0, south_deg=10.0, east_deg_east=80.0, north_deg=20.0)
    with pytest.raises(AreaTooLarge):
        check_availability("hydrated minerals", big, fetch_json=catalog({}), max_area_km2=2500.0)


def client(fetch):
    app = FastAPI()
    app.include_router(availability.router, prefix="/api/v1")
    app.dependency_overrides[availability.get_checker] = lambda: (lambda o, b, **kw: check_availability(o, b, fetch_json=fetch, **kw))
    return TestClient(app)


def test_endpoint_returns_the_documented_shape() -> None:
    c = client(catalog({"CRISM": payload(FULL)}))
    r = c.post("/api/v1/objectives/check", json={"objective": "find hydrated minerals", "bounds": AOI.model_dump()})
    assert r.status_code == 200
    out = r.json()
    assert set(out) == {"objective", "matched_objective_id", "supported", "message", "coverage", "warnings"}
    assert out["supported"] is True and out["matched_objective_id"] == "hydrated_minerals"
    assert set(out["coverage"][0]) == {"instrument", "product_type", "label", "measures", "covered_percent", "product_count", "example_product_ids", "analyzable", "note"}


def test_endpoint_validates_the_request() -> None:
    c = client(catalog({}))
    big = {"west_deg_east": 70.0, "south_deg": 10.0, "east_deg_east": 80.0, "north_deg": 20.0}
    assert c.post("/api/v1/objectives/check", json={"objective": "minerals", "bounds": big}).status_code == 422
    assert c.post("/api/v1/objectives/check", json={"objective": "", "bounds": AOI.model_dump()}).status_code == 422
    assert c.post("/api/v1/objectives/check", json={"objective": "x" * 301, "bounds": AOI.model_dump()}).status_code == 422
    flipped = {"west_deg_east": 80, "south_deg": 1, "east_deg_east": 70, "north_deg": 2}
    assert c.post("/api/v1/objectives/check", json={"objective": "minerals", "bounds": flipped}).status_code == 422
