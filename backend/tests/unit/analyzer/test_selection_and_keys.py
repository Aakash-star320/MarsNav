from uuid import uuid4

from app.analyzer.selection.selector import select_products
from app.analyzer.validation.cache_keys import analysis_result_key, processed_region_key, raw_product_key
from app.schemas import BoundingBox, CoverageStatus, DatasetCategory, DatasetCoverage, DatasetRecord, FreshnessState

AOI = BoundingBox(west_deg_east=0, south_deg=0, east_deg_east=1, north_deg=1)


def box(w, s, e, n):
    return BoundingBox(west_deg_east=w, south_deg=s, east_deg_east=e, north_deg=n)


def rec(pid, fp, res=None, cat=DatasetCategory.elevation, status=CoverageStatus.available, version="1"):
    return DatasetRecord(
        id=uuid4(), source="pds", product_id=pid, version=version, category=cat, resolution_m_per_px=res,
        coverage=DatasetCoverage(status=status, percent_of_aoi=100, footprint=fp),
        freshness=FreshnessState.up_to_date,
    )


def test_global_fallback_plus_partial_detail() -> None:
    sel = select_products(AOI, [
        rec("GLOBAL", box(-10, -10, 10, 10), 463),
        rec("DETAIL", box(0, 0, 0.5, 1), 25),
    ]).categories[0]
    assert [d.product_id for d in sel.selected] == ["DETAIL", "GLOBAL"]
    assert sel.covered_fraction == 1.0


def test_last_slot_is_reserved_for_widest_fallback() -> None:
    tiles = [rec(f"T{i}", box(0.1 * i, 0, 0.1 * i + 0.1, 0.1), 5) for i in range(5)]
    sel = select_products(AOI, [*tiles, rec("GLOBAL", box(-1, -1, 2, 2), 463)], max_per_category=3).categories[0]
    assert sel.selected[-1].product_id == "GLOBAL" and len(sel.selected) == 3


def test_finer_product_wins_ties_and_redundant_is_rejected() -> None:
    sel = select_products(AOI, [rec("COARSE", box(-1, -1, 2, 2), 463), rec("FINE", box(-1, -1, 2, 2), 20)]).categories[0]
    assert [d.product_id for d in sel.selected] == ["FINE"]
    assert [r.dataset.product_id for r in sel.rejected] == ["COARSE"]


def test_no_overlap_unavailable_and_duplicates_are_reported() -> None:
    res = select_products(AOI, [
        rec("OUT", box(50, 50, 60, 60)),
        rec("GONE", box(-1, -1, 2, 2), status=CoverageStatus.unavailable),
        rec("DUP", box(-1, -1, 2, 2), 10),
        rec("DUP", box(-1, -1, 2, 2), 10),
    ])
    reasons = {r.dataset.product_id + ":" + r.reason.split()[0] for r in res.categories[0].rejected}
    assert {"OUT:footprint", "GONE:coverage", "DUP:duplicate"} <= reasons
    assert [d.product_id for d in res.categories[0].selected] == ["DUP"]


def test_categories_are_never_substituted() -> None:
    res = select_products(AOI, [rec("DEM", box(-1, -1, 2, 2), 20), rec("SPEC", box(0, 0, 0.1, 0.1), 18, DatasetCategory.spectral)])
    spectral = next(c for c in res.categories if c.category == DatasetCategory.spectral)
    assert spectral.covered_fraction < 0.05  # the DEM does not fill spectral coverage


def test_no_candidates_yields_empty_result() -> None:
    assert select_products(AOI, []).categories == []


def test_selection_is_deterministic() -> None:
    cands = [rec("A", box(0, 0, 0.6, 1), 10), rec("B", box(0.4, 0, 1, 1), 10), rec("C", box(0, 0, 1, 1), 100)]
    assert select_products(AOI, cands) == select_products(AOI, list(reversed(cands)))


def test_cache_keys_are_stable_and_sensitive() -> None:
    args = dict(bounds=AOI, crs_wkt="WKT", product_versions={"a": "1"}, algorithm_version="v1",
                resolution_m=10.0, parameters={"slope": 12.0}, categories=["elevation", "thermal"])
    k1 = processed_region_key(**args)
    assert k1 == processed_region_key(**{**args, "categories": ["thermal", "elevation"]})
    assert k1 != processed_region_key(**{**args, "algorithm_version": "v2"})
    assert k1 != processed_region_key(**{**args, "product_versions": {"a": "2"}})
    assert raw_product_key("pds", "X", "1") != raw_product_key("pds", "X", "2")
    assert analysis_result_key(k1, "minerals", {"a": 1}) != analysis_result_key(k1, "thermal", {"a": 1})
