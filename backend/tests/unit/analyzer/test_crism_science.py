import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest

from app.analyzer.orchestration.pipeline import AnalyzerDeps, run_region_analysis
from app.analyzer.science import crism_parameters as cp
from app.analyzer.science.hydrated_minerals import DetectionConfig, detect, evidence_map
from app.analyzer.science.pipeline import ScienceDeps, discover, run_hydrated_minerals, wants_hydrated_minerals
from app.connectors.common.http import HttpFetchError
from app.connectors.pds.crism_mtrdr import parse_layout
from app.connectors.usgs.mola import MolaLayout
from app.schemas import BoundingBox, CreateAnalysisRequest, JobStage, LonLat, RegionOfInterest

FIX = Path(__file__).parents[2] / "fixtures" / "crism"
HDR = (FIX / "frt000047a3_07_su166j_mtr3.hdr").read_text(encoding="utf-8")
ODE_REPLY = json.loads((FIX / "ode_mtrdr_frt000047a3.json").read_text(encoding="utf-8"))
LAYOUT = parse_layout(HDR)
D2300, D2200, BD = cp.PHY.stretch_max("D2300"), cp.PHY.stretch_max("D2200"), cp.PHY.stretch_max("BD1900R2")
AOI = BoundingBox(west_deg_east=77.45, south_deg=18.50, east_deg_east=77.55, north_deg=18.60)


# -- documented definitions ------------------------------------------------------------------------
def test_definitions_match_the_recorded_pds_labels() -> None:
    recorded = json.loads((FIX / "browse_definitions.json").read_text(encoding="utf-8"))
    for code, d in cp.BROWSE.items():
        assert list(d.bands) == recorded[code]["bands"] and list(d.scaling) == pytest.approx(recorded[code]["scaling"])
    assert cp.PHY.stretch_max("D2300") == pytest.approx(254 * 1.3358e-4)
    assert set(cp.PHY.bands) <= set(LAYOUT.band_names) and set(cp.HYD.bands) <= set(LAYOUT.band_names)   # real bands of the cube


# -- detector --------------------------------------------------------------------------------------
def planted(shape=(60, 60)):
    z = np.zeros(shape, dtype=np.float32)
    b = {"D2300": z.copy(), "D2200": z.copy(), "BD1900R2": z.copy()}
    b["D2300"][10:20, 10:20] = 0.9 * D2300           # hydrated Fe/Mg-OH signature: OH + hydration, 100 pixels
    b["BD1900R2"][10:20, 10:20] = 0.9 * BD
    b["D2300"][30:40, 30:40] = 0.9 * D2300           # OH band without hydration: must not be a candidate
    b["BD1900R2"][45:55, 5:15] = 0.9 * BD            # hydration without an OH band: must not be a candidate
    b["D2200"][40:46, 40:50] = 0.8 * D2200           # hydrated Al/Si-OH signature, 60 pixels
    b["BD1900R2"][40:46, 40:50] = 0.8 * BD
    return b


def test_only_oh_plus_hydration_counts_and_location_is_exact() -> None:
    cands = detect(planted())
    assert len(cands) == 2
    big, small = cands[0], cands[1]
    assert big.pixels == 100 and (big.row, big.col) == pytest.approx((15.0, 15.0)) and big.dominant_oh == "D2300"
    assert small.pixels == 60 and small.dominant_oh == "D2200"
    assert big.mean_evidence == pytest.approx(0.9) and big.rank_score == pytest.approx(0.7 * 0.9 + 0.3 * 100 / 400)
    assert big.confidence == "medium" and small.confidence == "low"             # strength and extent only


def test_threshold_size_filter_and_limit_are_respected() -> None:
    assert len(detect(planted(), DetectionConfig(threshold_fraction=0.95))) == 0
    assert len(detect(planted(), DetectionConfig(min_pixels=80))) == 1
    assert len(detect(planted(), DetectionConfig(max_candidates=1))) == 1
    with pytest.raises(ValueError):
        DetectionConfig(threshold_fraction=0)


def test_missing_data_is_not_evidence() -> None:
    b = planted()
    for k in b:
        b[k][10:20, 10:20] = np.nan                  # the strong block has no data
    e, valid = evidence_map(b)
    assert np.isnan(e[12, 12]) and not valid[12, 12]
    assert [c.pixels for c in detect(b)] == [60]       # nothing is invented where data are missing


def test_negative_values_clip_to_no_evidence_and_bad_input_is_rejected() -> None:
    b = {k: np.full((5, 5), -1.0, dtype=np.float32) for k in ("D2300", "D2200", "BD1900R2")}
    e, _ = evidence_map(b)
    assert np.all(e == 0.0)
    with pytest.raises(ValueError):
        detect({"D2300": b["D2300"]})
    with pytest.raises(ValueError):
        detect({**b, "D2200": np.zeros((4, 4), dtype=np.float32)})


def test_detection_is_deterministic() -> None:
    assert detect(planted()) == detect(planted())


# -- science stage over a synthetic cube with the real layout ---------------------------------------
class FakeCube:
    """Serves byte ranges of a 60-band cube: three real bands get the planted arrays, the others are zero."""

    def __init__(self, bands: dict[str, np.ndarray]) -> None:
        self.bands = {LAYOUT.band_index(n): a.astype("<f4") for n, a in bands.items()}
        self.calls: list[tuple[int, int]] = []

    def __call__(self, first: int, last: int) -> bytes:
        self.calls.append((first, last))
        idx = first // LAYOUT.band_bytes
        full = self.bands.get(idx, np.zeros((LAYOUT.lines, LAYOUT.samples), dtype="<f4")).tobytes()
        off = first - idx * LAYOUT.band_bytes
        return full[off:off + (last - first + 1)]


def cube_with_blob(center: LonLat, half: int = 8, nan_corner: bool = False):
    r, c = LAYOUT.lonlat_to_rowcol(center)
    r, c = int(r), int(c)
    arrays = {n: np.zeros((LAYOUT.lines, LAYOUT.samples), dtype=np.float32) for n in ("D2300", "D2200", "BD1900R2")}
    arrays["D2300"][r - half:r + half, c - half:c + half] = 0.9 * D2300
    arrays["BD1900R2"][r - half:r + half, c - half:c + half] = 0.9 * BD
    return arrays


def science_deps(cube: FakeCube, reply=ODE_REPLY, **kw) -> ScienceDeps:
    return ScienceDeps(fetch_json=lambda url: reply, fetch_text=lambda url: HDR, range_fetcher_for=lambda url: cube, **kw)


CENTER = LonLat(latitude_deg=18.55, longitude_deg_east=77.50)


def test_discovery_selects_the_summary_parameter_file() -> None:
    recs = discover(AOI, science_deps(FakeCube({})))
    assert len(recs) == 1 and recs[0].product_id == "frt000047a3_07_if166j_mtr3"
    assert str(recs[0].download_url).lower().endswith("_su166j_mtr3.img") and recs[0].category.value == "spectral"


def test_end_to_end_finds_the_planted_signature_with_traceable_evidence() -> None:
    cube = FakeCube(cube_with_blob(CENTER))
    out = run_hydrated_minerals(AOI, science_deps(cube))
    assert len(out.targets) == 1 and out.datasets[0].product_id == "frt000047a3_07_if166j_mtr3"
    t = out.targets[0]
    assert abs(t.location.latitude_deg - CENTER.latitude_deg) < 0.001 and abs(t.location.longitude_deg_east - CENTER.longitude_deg_east) < 0.001
    assert t.objective_category == "hydrated_minerals" and 0 <= t.relevance_score <= 1 and t.confidence in {"low", "medium"}
    measured, heuristic = t.evidence
    assert measured.measured and "D2300 = " in measured.statement and "PHY" not in measured.statement
    assert not heuristic.measured and "Viviano-Beck" in heuristic.statement and "heuristic" in " ".join(heuristic.limitations).lower()
    assert any("not evidence of absence" in s for s in heuristic.limitations)
    assert len(cube.calls) == 3 and all(b - a + 1 <= 808 * 847 * 4 for a, b in cube.calls)      # three bands, one range request each
    assert out.provenance.recipe_version == "crism-hydrated/1" and any("not identified minerals" in w for w in out.warnings)


def test_no_coverage_discovery_failure_and_unreadable_product_are_soft_warnings() -> None:
    empty = {"ODEResults": {"Status": "Success", "Products": {}}}
    out = run_hydrated_minerals(AOI, science_deps(FakeCube({}), reply=empty))
    assert out.targets == [] and "not evidence of absence" in out.warnings[0]

    def boom(url):
        raise HttpFetchError("unreachable", "no route to host")
    down = ScienceDeps(fetch_json=boom, fetch_text=lambda u: HDR, range_fetcher_for=lambda u: FakeCube({}))
    out = run_hydrated_minerals(AOI, down)
    assert out.targets == [] and "discovery failed" in out.warnings[0]

    def bad_fetch(a, b):
        raise TimeoutError("slow server")
    out = run_hydrated_minerals(AOI, science_deps(bad_fetch))
    assert out.targets == [] and any("could not be read" in w for w in out.warnings)


def test_all_missing_data_gives_no_targets_and_says_so() -> None:
    zeros_nan = {n: np.full((LAYOUT.lines, LAYOUT.samples), 65535.0, dtype=np.float32) for n in ("D2300", "D2200", "BD1900R2")}
    out = run_hydrated_minerals(AOI, science_deps(FakeCube(zeros_nan)))
    assert out.targets == [] and any("no valid pixels" in w for w in out.warnings)


def test_a_clean_area_reports_no_candidate_without_claiming_absence() -> None:
    clean = {n: np.zeros((LAYOUT.lines, LAYOUT.samples), dtype=np.float32) for n in ("D2300", "D2200", "BD1900R2")}
    out = run_hydrated_minerals(AOI, science_deps(FakeCube(clean)))
    assert out.targets == [] and any("not evidence that hydrated minerals are absent" in w for w in out.warnings)


def test_objective_wording() -> None:
    assert wants_hydrated_minerals("Find hydrated minerals") and wants_hydrated_minerals("clay-bearing sites")
    assert not wants_hydrated_minerals("terrain overview")


# -- inside the analysis pipeline ------------------------------------------------------------------
SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
_r, _c = np.indices((SMALL.height, SMALL.width))
BLOB = b"\0" * SMALL.data_offset + (10 * _r + 100 * _c).astype("<i2").tobytes()
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def analysis(tmp_path, objective, science):
    deps = AnalyzerDeps(fetch_range=lambda a, b: BLOB[a:b + 1], out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9, science=science)
    req = CreateAnalysisRequest(mission_id=uuid4(), objective=objective, roi=RegionOfInterest(name="t", bounds=AOI, analysis_margin_m=0))
    seen = []
    return run_region_analysis(uuid4(), req, deps, lambda s, p, m: seen.append(s), NOW), seen


def test_analysis_with_a_science_objective_returns_targets_and_datasets(tmp_path) -> None:
    result, stages = analysis(tmp_path, "find hydrated minerals", science_deps(FakeCube(cube_with_blob(CENTER))))
    assert JobStage.science in stages and len(result.science_targets) == 1
    assert len(result.datasets) == 2 and result.datasets[0].instrument == "MOLA" and result.datasets[1].category.value == "spectral"
    assert any(p.recipe_version == "crism-hydrated/1" for p in result.processing_provenance)
    assert any("Spectral candidates" in w for w in result.warnings)


def test_other_objectives_do_not_touch_the_science_services(tmp_path) -> None:
    cube = FakeCube(cube_with_blob(CENTER))
    result, stages = analysis(tmp_path, "terrain overview", science_deps(cube))
    assert JobStage.science not in stages and cube.calls == [] and result.science_targets == []
    assert any("not interpreted" in w for w in result.warnings)


def test_science_failure_never_fails_the_terrain_analysis(tmp_path) -> None:
    def boom(url):
        raise HttpFetchError("unreachable", "down")
    result, _ = analysis(tmp_path, "hydrated minerals", ScienceDeps(fetch_json=boom, fetch_text=lambda u: HDR, range_fetcher_for=lambda u: FakeCube({})))
    assert result.science_targets == [] and len(result.layers) == 5 and any("discovery failed" in w for w in result.warnings)
