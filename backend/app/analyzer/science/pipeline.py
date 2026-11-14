"""Science stage: find CRISM MTRDR observations over the area, read three summary-parameter bands,
detect hydrated hydroxylated-mineral candidates, and return contract objects.

Failures never abort the terrain analysis: a missing service, no coverage or an unreadable product
becomes a warning and an empty target list. Missing observations are never reported as absence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

import numpy as np

from app.analyzer.discovery.mars_geometry import haversine_m
from app.connectors.common.http import HttpFetchError
from app.connectors.ode.ode_rest import OdeError, build_product_query, parse_product_results
from app.connectors.pds.crism_mtrdr import CrismError, RangeFetcher, SummaryCubeLayout, parse_layout, pixel_window, read_band_window
from app.schemas import (
    BoundingBox,
    DatasetCategory,
    DatasetRecord,
    LonLat,
    ProcessingProvenance,
    ScienceEvidence,
    ScienceTarget,
)

from .crism_parameters import LITERATURE, PDS_BUNDLE_URL, PDS_DATASET_ID, PHY
from .hydrated_minerals import REQUIRED_BANDS, Candidate, DetectionConfig, detect, evidence_map

OBJECTIVE_WORDS = ("hydrated", "mineral", "clay", "phyllosilicate", "smectite", "science")
SU_PATTERN = r"_SU\d+J_MTR3\.IMG$"
RECIPE = "crism-hydrated/1"
DEDUPE_METRES = 100.0


@dataclass(frozen=True)
class ScienceDeps:
    fetch_json: Callable[[str], dict[str, Any]]
    fetch_text: Callable[[str], str]
    range_fetcher_for: Callable[[str], RangeFetcher]
    max_observations: int = 2
    max_bytes: int = 32 * 1024 * 1024
    config: DetectionConfig = field(default_factory=DetectionConfig)


@dataclass(frozen=True)
class EvidenceRaster:
    values: np.ndarray
    bounds: BoundingBox
    product_id: str
    pixel_m: float
    valid_pixels: int


@dataclass
class ScienceOutcome:
    targets: list[ScienceTarget] = field(default_factory=list)
    datasets: list[DatasetRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: ProcessingProvenance | None = None
    attempted: bool = True
    evidence: EvidenceRaster | None = None      # best-covered observation, for the map overlay


def wants_hydrated_minerals(objective: str) -> bool:
    text = objective.lower()
    return any(w in text for w in OBJECTIVE_WORDS)


def discover(bounds: BoundingBox, deps: ScienceDeps, limit: int = 25) -> list[DatasetRecord]:
    url = build_product_query(bounds, ihid="MRO", iid="CRISM", pt="MTRDR", results="mpf", limit=limit, loc="f")
    records = parse_product_results(deps.fetch_json(url), category=DatasetCategory.spectral, aoi=bounds, file_pattern=SU_PATTERN)
    usable = [r for r in records if r.download_url is not None and r.coverage.footprint is not None]
    return sorted(usable, key=lambda r: (-r.coverage.percent_of_aoi, r.product_id))


def _header_url(record: DatasetRecord) -> str:
    url = str(record.download_url)
    if not url.lower().endswith(".img"):
        raise CrismError("bad_url", f"unexpected product file name: {url}")
    return url[:-4] + ".hdr"


def _target(c: Candidate, layout: SummaryCubeLayout, window: tuple[int, int, int, int], record: DatasetRecord, cfg: DetectionConfig) -> ScienceTarget:
    row0, _, col0, _ = window
    p = layout.rowcol_to_lonlat(row0 + c.row, col0 + c.col)
    area_m2 = c.pixels * layout.pixel_m ** 2
    stretch = {b: PHY.stretch_max(b) for b in REQUIRED_BANDS}
    values = ", ".join(f"{b} = {c.mean_values[b]:.4f} ({100 * c.mean_normalised[b]:.0f}% of the browse stretch {stretch[b]:.4f})" for b in REQUIRED_BANDS)
    limitations = [
        "Heuristic threshold, not a published detection criterion.",
        "Positive mineral identification requires analysis of the CRISM spectrum (PDS label).",
        "Absence of a candidate is not evidence of absence.",
    ]
    source = str(record.provenance_url) if record.provenance_url else PDS_BUNDLE_URL
    return ScienceTarget(
        id=uuid5(NAMESPACE_URL, f"{record.product_id}:{round(p.latitude_deg, 6)}:{round(p.longitude_deg_east, 6)}"),
        location=p,
        title=f"Hydrated hydroxylated-mineral candidate ({c.dominant_oh} with BD1900R2)",
        objective_category="hydrated_minerals", relevance_score=round(min(1.0, max(0.0, c.rank_score)), 4), confidence=c.confidence,
        rank_explanation=(f"rank = 0.7 x mean evidence ({c.mean_evidence:.2f}) + 0.3 x min(1, pixels/400) ({min(1.0, c.pixels / 400):.2f}); "
                          f"evidence = min(max(D2300, D2200), BD1900R2) as a fraction of the PDS browse-product stretch; "
                          f"confidence reflects strength and extent only, not mineral identity"),
        evidence=[
            ScienceEvidence(dataset_id=record.id, statement=f"CRISM {record.product_id}: mean summary parameters over {c.pixels} pixels "
                            f"({area_m2:,.0f} m2): {values}. Values are dimensionless band-depth/index values.",
                            measured=True, source_uri=source, limitations=limitations),
            ScienceEvidence(dataset_id=record.id, statement=(f"Candidate rule: min(max(D2300, D2200), BD1900R2) normalised by the stretch of the PDS PHY browse product "
                            f"is at least {cfg.threshold_fraction:g} on at least {cfg.min_pixels} connected pixels. {LITERATURE}."),
                            measured=False, source_uri=PDS_BUNDLE_URL, limitations=limitations),
        ],
    )


def run_hydrated_minerals(bounds: BoundingBox, deps: ScienceDeps) -> ScienceOutcome:
    out = ScienceOutcome()
    try:
        records = discover(bounds, deps)
    except (OdeError, HttpFetchError, ValueError, KeyError) as exc:
        out.warnings.append(f"CRISM discovery failed ({exc}); no spectral candidates were produced. This is not evidence that none exist.")
        return out
    if not records:
        out.warnings.append("No CRISM targeted observation (MTRDR summary parameters) covers this area, so no spectral candidates were produced. Missing coverage is not evidence of absence.")
        return out
    used: list[str] = []
    valid_fractions: list[float] = []
    for rec in records:
        if len(used) >= deps.max_observations:
            break
        try:
            layout = parse_layout(deps.fetch_text(_header_url(rec)))
            window = pixel_window(layout, bounds)
            if window is None:
                continue
            fetch = deps.range_fetcher_for(str(rec.download_url))
            bands = {b: read_band_window(layout, b, window, fetch, deps.max_bytes).values for b in REQUIRED_BANDS}
        except (CrismError, HttpFetchError, OdeError, ValueError) as exc:
            out.warnings.append(f"CRISM observation {rec.product_id} could not be read ({getattr(exc, 'code', type(exc).__name__)}: {exc}).")
            continue
        except Exception as exc:  # network layers raise several types; any read failure must not abort the analysis
            out.warnings.append(f"CRISM observation {rec.product_id} could not be read ({type(exc).__name__}).")
            continue
        valid = np.logical_and.reduce([np.isfinite(bands[b]) for b in REQUIRED_BANDS])
        if not valid.any():
            out.warnings.append(f"CRISM observation {rec.product_id} has no valid pixels in this area.")
            continue
        used.append(rec.product_id)
        n_valid = int(valid.sum())
        if out.evidence is None or n_valid > out.evidence.valid_pixels:
            ev, _ = evidence_map(bands)
            nw, se = layout.rowcol_to_lonlat(window[0], window[2]), layout.rowcol_to_lonlat(window[1], window[3])
            out.evidence = EvidenceRaster(values=ev.astype(np.float32), bounds=BoundingBox(west_deg_east=nw.longitude_deg_east, south_deg=se.latitude_deg, east_deg_east=se.longitude_deg_east, north_deg=nw.latitude_deg), product_id=rec.product_id, pixel_m=layout.pixel_m, valid_pixels=n_valid)
        valid_fractions.append(float(valid.mean()))
        out.datasets.append(rec)
        for cand in detect(bands, deps.config):
            t = _target(cand, layout, window, rec, deps.config)
            inside = bounds.west_deg_east <= t.location.longitude_deg_east <= bounds.east_deg_east and bounds.south_deg <= t.location.latitude_deg <= bounds.north_deg
            near = any(haversine_m(t.location, o.location) < DEDUPE_METRES for o in out.targets)
            if inside and not near:
                out.targets.append(t)
    if not used:
        out.warnings.append("No CRISM observation could be used for this area; no spectral candidates were produced.")
        return out
    out.targets.sort(key=lambda t: (-t.relevance_score, t.location.latitude_deg, t.location.longitude_deg_east))
    out.targets = out.targets[: deps.config.max_candidates]
    out.warnings.append(
        f"Spectral candidates come from CRISM observation(s) {', '.join(used)}; valid data covers {100 * max(valid_fractions):.0f}% of the area's bounding window "
        "at best. Candidates are a heuristic screen of summary parameters, not identified minerals; check the spectrum before relying on one.")
    if not out.targets:
        out.warnings.append("No candidate met the rule in the covered part of the area. This is not evidence that hydrated minerals are absent.")
    out.provenance = ProcessingProvenance(
        recipe_version=RECIPE,
        parameters={"dataset": PDS_DATASET_ID, "products": used, "bands": list(REQUIRED_BANDS), "threshold_fraction": deps.config.threshold_fraction,
                    "min_pixels": deps.config.min_pixels, "stretch": {b: PHY.stretch_max(b) for b in REQUIRED_BANDS}},
    )
    return out
