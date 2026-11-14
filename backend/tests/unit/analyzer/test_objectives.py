from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.analyzer.orchestration.pipeline import AnalyzerDeps, run_region_analysis
from app.analyzer.preprocessing.terrain_bundle import _grid
from app.analyzer.science import terrain_objectives as T
from app.analyzer.science.objectives import FLAT_SITES, HYDRATED, VANTAGE, get_objective, list_objectives, resolve_objective, supported_labels
from app.connectors.usgs.mola import MolaLayout
from app.schemas import BoundingBox, CreateAnalysisRequest, RegionOfInterest

AID, DID = UUID("00000000-0000-0000-0000-00000000a001"), UUID("00000000-0000-0000-0000-00000000d001")
BOUNDS = BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=30.0, north_deg=40.0)      # 40 x 40 cells of 0.5 degrees
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def arrays(rows=40, cols=40, slope=20.0, rough=5.0, elevation=100.0):
    return {"elevation_m": np.full((rows, cols), elevation, np.float32), "slope_deg": np.full((rows, cols), slope, np.float32),
            "roughness_m": np.full((rows, cols), rough, np.float32), "valid": np.ones((rows, cols), bool)}


def grid_for(a):
    return _grid(BOUNDS, a["valid"].shape)


def flat(a, r0, r1, c0, c1, slope=1.0, rough=0.1):
    a["slope_deg"][r0:r1, c0:c1] = slope
    a["roughness_m"][r0:r1, c0:c1] = rough


def sites(a):
    return T.find_flat_safe_sites(a, BOUNDS, grid_for(a), AID, DID, "https://example.test/mola")


def hills(a):
    return T.find_high_vantage_points(a, BOUNDS, grid_for(a), AID, DID, "https://example.test/mola")


def hill(a, row, col, height, sigma=2.0):
    r, c = np.indices(a["elevation_m"].shape)
    a["elevation_m"] += (height * np.exp(-((r - row) ** 2 + (c - col) ** 2) / (2 * sigma ** 2))).astype(np.float32)
    a["slope_deg"][:] = 3.0                                                         # gentle everywhere unless a test says otherwise


# -- the registry -----------------------------------------------------------------------------------------
def test_the_registry_lists_the_supported_objectives_with_their_limits() -> None:
    items = list_objectives()
    assert [o.id for o in items] == [HYDRATED, FLAT_SITES, VANTAGE]
    assert {o.kind for o in items} == {"spectral", "terrain"}
    assert all(o.label and o.description and o.keywords and o.data_used and o.limitation for o in items)
    assert supported_labels() == "Hydrated minerals, Flat safe sites, High vantage points" and get_objective("nope") is None


@pytest.mark.parametrize("text, expected", [
    ("hydrated_minerals", HYDRATED), ("Hydrated minerals", HYDRATED), ("find hydrated minerals", HYDRATED), ("Clay mineral signatures", HYDRATED),
    ("clay-bearing sites", HYDRATED), ("science", HYDRATED), ("Flat safe sites", FLAT_SITES), ("flat safe sites for science", FLAT_SITES),
    ("find a safe landing site", FLAT_SITES), ("somewhere on level ground to set up camp", FLAT_SITES), ("High vantage points", VANTAGE),
    ("I need the highest point nearby", VANTAGE), ("an overlook with a view", VANTAGE), ("hilltops and peaks", VANTAGE),
    ("terrain overview", None), ("Geological diversity", None), ("Thermal properties", None), ("Interesting terrain", None), ("", None),
    ("speak to the crew", None),                     # "peak" must not match inside another word
])
def test_resolve_objective(text, expected) -> None:
    assert resolve_objective(text) == expected


# -- flat safe sites ------------------------------------------------------------------------------------------
def test_a_flat_smooth_plateau_becomes_one_ranked_target_with_measured_and_heuristic_evidence() -> None:
    a = arrays()
    flat(a, 10, 22, 20, 32)                                                         # a 12 x 12 patch
    out = sites(a)
    assert len(out.targets) == 1 and not out.warnings
    t = out.targets[0]
    assert t.objective_category == FLAT_SITES and t.confidence == "medium" and 0.5 < t.relevance_score <= 1
    assert t.location == T._centre(BOUNDS, (40, 40), 15, 25)                         # the patch cell nearest its centroid, ties to the smaller row and column
    assert BOUNDS.south_deg <= t.location.latitude_deg <= BOUNDS.north_deg and BOUNDS.west_deg_east <= t.location.longitude_deg_east <= BOUNDS.east_deg_east
    assert [e.measured for e in t.evidence] == [True, True, False]                  # measured values first, then the heuristic rule
    assert "144 valid cells" in t.evidence[0].statement and "heuristic" in t.evidence[-1].statement.lower()
    assert all(e.limitations and e.dataset_id == DID and e.source_uri == "https://example.test/mola" for e in t.evidence)
    assert "not a surveyed landing site" in " ".join(t.evidence[0].limitations) and "rank 1 of 1" in t.rank_explanation


def test_bigger_and_flatter_patches_rank_higher_and_at_most_five_are_returned() -> None:
    a = arrays(rows=60, cols=60)
    big = (slice(2, 14), slice(2, 14))
    a["slope_deg"][big], a["roughness_m"][big] = 0.5, 0.1
    for k in range(7):                                                              # seven small patches, 3 x 3 cells each
        r0 = 20 + 5 * (k // 3)
        c0 = 4 + 7 * (k % 3)
        flat(a, r0, r0 + 3, c0, c0 + 3, slope=2.0)
    out = T.find_flat_safe_sites(a, BOUNDS, _grid(BOUNDS, (60, 60)), AID, DID)
    assert len(out.targets) == 5
    scores = [t.relevance_score for t in out.targets]
    assert scores == sorted(scores, reverse=True) and out.targets[0].title.startswith("Flat, smooth patch of 144 cells")


def test_patches_that_are_too_small_steep_or_empty_give_no_target_and_say_why() -> None:
    small = arrays(); flat(small, 5, 7, 5, 9)                                       # 8 cells: below the 9-cell minimum
    assert sites(small).targets == [] and "at least 9 cells" in sites(small).warnings[0]
    assert sites(arrays(slope=30.0)).targets == [] and sites(arrays(slope=30.0)).warnings
    none = arrays(); none["valid"][:] = False
    out = sites(none)
    assert out.targets == [] and "no flat sites" in out.warnings[0].lower()


def test_invalid_cells_never_count_as_flat_ground() -> None:
    a = arrays(); flat(a, 10, 22, 20, 32)
    a["valid"][10:22, 20:26] = False                                                # half the patch has no data
    out = sites(a)
    assert len(out.targets) == 1 and "72 valid cells" in out.targets[0].evidence[0].statement


# -- high vantage points ----------------------------------------------------------------------------------------
def test_a_hill_gives_one_target_at_its_top_with_prominence() -> None:
    a = arrays(); hill(a, 20, 20, 150.0)
    out = hills(a)
    assert len(out.targets) == 1
    t = out.targets[0]
    assert t.objective_category == VANTAGE and t.confidence == "medium" and 0.6 < t.relevance_score <= 1
    assert t.location == T._centre(BOUNDS, (40, 40), 20, 20)
    assert [e.measured for e in t.evidence] == [True, True, False] and "above the median" in t.evidence[0].statement
    assert "Line of sight" in " ".join(t.evidence[0].limitations)


def test_a_flat_topped_rise_is_one_point_and_a_low_bump_or_steep_summit_is_not_offered() -> None:
    a = arrays(); a["elevation_m"][18:22, 18:22] += 80.0; a["slope_deg"][:] = 2.0   # a small flat-topped rise: 16 cells at the same height
    assert len(hills(a).targets) == 1 and "80 m above" in hills(a).targets[0].evidence[0].statement
    wide = arrays(); wide["elevation_m"][10:30, 10:30] += 80.0; wide["slope_deg"][:] = 2.0
    assert hills(wide).targets == []                                                # a wide plateau is not a rise: it fills its own comparison window
    low = arrays(); hill(low, 20, 20, 10.0)                                         # 10 m: below the 25 m minimum
    assert hills(low).targets == [] and "stands at least 25 m" in hills(low).warnings[0]
    steep = arrays(); hill(steep, 20, 20, 150.0); steep["slope_deg"][20, 20] = 30.0
    assert hills(steep).targets == []


def test_hills_at_the_edge_or_next_to_missing_data_are_not_reported() -> None:
    edge = arrays(); hill(edge, 1, 1, 200.0)
    assert hills(edge).targets == []                                                # the 5 x 5 block would leave the area
    gap = arrays(); hill(gap, 20, 20, 200.0); gap["valid"][19, 19] = False
    assert hills(gap).targets == []                                                 # a hole next to the top: its height is not trustworthy


def test_vantage_points_are_ranked_by_prominence_and_capped_at_five() -> None:
    a = arrays(rows=60, cols=60)
    for k in range(7):
        hill(a, 8 + 8 * (k % 4), 8 + 14 * (k // 4) + 8 * (k % 2), 40.0 + 20.0 * k, sigma=1.5)
    out = T.find_high_vantage_points(a, BOUNDS, _grid(BOUNDS, (60, 60)), AID, DID)
    assert 1 <= len(out.targets) <= 5
    scores = [t.relevance_score for t in out.targets]
    assert scores == sorted(scores, reverse=True)


def test_a_tiny_area_or_no_data_says_so() -> None:
    assert hills(arrays(rows=4, cols=4)).targets == [] and hills(arrays(rows=4, cols=4)).warnings
    none = arrays(); none["valid"][:] = False
    assert hills(none).targets == [] and hills(none).warnings


def test_the_detectors_are_deterministic() -> None:
    a = arrays(); flat(a, 10, 22, 20, 32); hill(a, 30, 8, 120.0)
    a["slope_deg"][10:22, 20:32] = 1.0
    for fn in (sites, hills):
        first, second = fn(a), fn(a)
        assert [t.model_dump() for t in first.targets] == [t.model_dump() for t in second.targets]


# -- through the analysis pipeline ----------------------------------------------------------------------------------
SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5, pixel_size_m=1000.0, file_size=0, etag="test")
_r, _c = np.indices((SMALL.height, SMALL.width))
_hill = 400 * np.exp(-((_r - 120) ** 2 + (_c - 410) ** 2) / 8.0)
BLOB = b"\0" * SMALL.data_offset + (100 + _hill).astype("<i2").tobytes()          # a flat plain with one hill


def run(tmp_path, objective):
    deps = AnalyzerDeps(fetch_range=lambda a, b: BLOB[a:b + 1], out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9)
    roi = RegionOfInterest(name="t", bounds=BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=40.0, north_deg=40.0), analysis_margin_m=0)
    return run_region_analysis(uuid4(), CreateAnalysisRequest(mission_id=uuid4(), roi=roi, objective=objective), deps, lambda *a: None, NOW)


def test_the_pipeline_finds_the_hill_for_a_vantage_objective(tmp_path) -> None:
    res = run(tmp_path, "high vantage points")
    assert len(res.science_targets) >= 1 and all(t.objective_category == VANTAGE for t in res.science_targets)
    top = res.science_targets[0]
    assert abs(top.location.latitude_deg - (90 - 120.5 * 0.5)) < 1.0 and abs(top.location.longitude_deg_east - (-180 + 410.5 * 0.5)) < 1.0
    assert any(p.recipe_version == T.RECIPE_VANTAGE for p in res.processing_provenance)
    assert any("heuristic rule" in w for w in res.warnings) and not any("not interpreted" in w for w in res.warnings)


def test_the_pipeline_finds_flat_ground_for_a_flat_site_objective(tmp_path) -> None:
    res = run(tmp_path, "flat safe sites")
    assert len(res.science_targets) >= 1 and all(t.objective_category == FLAT_SITES for t in res.science_targets)
    assert any(p.recipe_version == T.RECIPE_FLAT for p in res.processing_provenance)


@pytest.mark.parametrize("objective", ["terrain overview", "Thermal properties", "boxwork formations"])
def test_unknown_objectives_still_give_terrain_only_and_list_what_is_supported(tmp_path, objective) -> None:
    res = run(tmp_path, objective)
    assert res.science_targets == []
    note = next(w for w in res.warnings if "not interpreted" in w)
    assert "Flat safe sites" in note and "High vantage points" in note and "Hydrated minerals" in note


def test_hydrated_minerals_without_the_science_service_is_unchanged(tmp_path) -> None:
    res = run(tmp_path, "find hydrated minerals")
    assert res.science_targets == [] and any("not interpreted" in w and "CRISM" in w for w in res.warnings)


def test_the_pipeline_result_is_repeatable(tmp_path) -> None:
    a, b = run(tmp_path / "a", "high vantage points"), run(tmp_path / "b", "high vantage points")
    assert [(t.location, t.relevance_score, t.title) for t in a.science_targets] == [(t.location, t.relevance_score, t.title) for t in b.science_targets]


# -- the endpoint -------------------------------------------------------------------------------------------------------
def test_the_objectives_endpoint_lists_every_objective_with_its_data_and_limits() -> None:
    from app.main import app
    r = TestClient(app).get("/api/v1/objectives")
    assert r.status_code == 200
    body = r.json()
    assert [o["id"] for o in body] == [HYDRATED, FLAT_SITES, VANTAGE]
    for o in body:
        assert set(o) == {"id", "label", "description", "keywords", "data_used", "limitation", "kind"}
        assert o["keywords"] and o["data_used"] and o["limitation"] and o["kind"] in ("spectral", "terrain")
