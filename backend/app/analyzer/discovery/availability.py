"""Does NASA have data for an objective in this area, and can this tool use it?

The user (or the assistant) names an objective in free text. This module:
1. says whether it is one of the objectives this tool can analyse (helper registry, or a small local fallback);
2. matches the words against a short, curated catalog of Mars instruments and product types that the ODE REST
   catalog understands (every ``ihid``/``iid``/``pt`` below was checked against ODE's own instrument list);
3. asks ODE which of those products cover the area and how much of it they cover;
4. answers honestly: supported and covered, covered but not analysable here, nothing listed, or "could not reach the
   catalog". A network failure never becomes a claim that no data exists.

Only "does a product's footprint overlap the area" is checked. Nothing is downloaded, and having data is not the
same as being able to answer the science question: ``analyzable`` is true only for what this tool can really process.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from app.analyzer.discovery.mars_geometry import bounds_area_m2
from app.analyzer.selection.selector import select_products
from app.connectors.common.http import HttpFetchError, get_json
from app.connectors.ode.ode_rest import OdeError, build_product_query, parse_product_results
from app.schemas import BoundingBox, DatasetCategory

try:                                                   # helper A's objective registry; a small local check keeps this module testable alone
    from app.analyzer.science.objectives import resolve_objective as _registry_resolve
except ImportError:                                     # pragma: no cover - exercised before the registry exists
    _registry_resolve = None

QUERY_LIMIT = 25
QUERY_TIMEOUT_S = 10.0
FetchJson = Callable[[str], dict[str, Any]]


class AvailabilityRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=300)
    bounds: BoundingBox


class CoverageItem(BaseModel):
    instrument: str
    product_type: str
    label: str
    measures: str
    covered_percent: float | None = None
    product_count: int = 0
    example_product_ids: list[str] = Field(default_factory=list)
    analyzable: bool
    note: str


class AvailabilityResult(BaseModel):
    objective: str
    matched_objective_id: str | None = None
    supported: bool = False
    message: str
    coverage: list[CoverageItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AreaTooLarge(ValueError):
    """The box is larger than one analysis may cover; the endpoint answers 422."""


@dataclass(frozen=True)
class CatalogEntry:
    instrument: str
    ihid: str
    iid: str
    pt: str
    label: str
    measures: str
    category: DatasetCategory
    keywords: tuple[str, ...]
    analyzable: bool = False


# Verified against ODE's own list of instrument / product-type combinations (query=iipt). `analyzable` is True only
# where this tool has a method: the MOLA elevation derivatives and the CRISM summary-parameter screen.
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry("CRISM", "MRO", "CRISM", "MTRDR", "CRISM map-projected targeted spectra (summary parameters)",
                 "mineral absorption features in visible to near-infrared spectra", DatasetCategory.spectral,
                 ("mineral", "spectr", "clay", "phyllosilicate", "smectite", "hydrated", "hydrous", "sulfate", "carbonate",
                  "silica", "composition", "alteration", "water-bearing"), analyzable=True),
    CatalogEntry("MOLA", "MGS", "MOLA", "MEGDR", "MOLA gridded elevation",
                 "global elevation (463 m) from laser altimetry", DatasetCategory.elevation,
                 ("elevation", "topograph", "slope", "terrain", "relief", "altitude", "height", "high ground", "vantage",
                  "flat", "ridge", "scarp", "rim", "crater", "landing", "safe site", "lowland", "highland"), analyzable=True),
    CatalogEntry("HiRISE terrain model", "MRO", "HIRISE", "DTM", "HiRISE digital terrain model",
                 "metre-scale terrain (about 1 m) for selected sites", DatasetCategory.elevation,
                 ("high-resolution terrain", "fine terrain", "terrain model", "boulder", "rock", "hazard", "obstacle",
                  "slope detail", "dtm")),
    CatalogEntry("HiRISE imagery", "MRO", "HIRISE", "RDRV11", "HiRISE map-projected images",
                 "very high resolution images (about 25 to 50 cm per pixel)", DatasetCategory.imagery,
                 ("boulder", "rock", "outcrop", "boxwork", "layer", "dune", "ripple", "texture", "morpholog", "fracture",
                  "high-resolution image", "high resolution image", "fine detail", "polygon", "gully")),
    CatalogEntry("CTX imagery", "MRO", "CTX", "EDR", "CTX context images (raw)",
                 "6 m context images; raw products that need processing before they can be mapped", DatasetCategory.imagery,
                 ("context image", "morpholog", "geolog", "landform", "channel", "valley", "delta", "image", "visible")),
    CatalogEntry("HRSC terrain", "MEX", "HRSC", "DTMRDR", "HRSC orthophotos and terrain models",
                 "stereo terrain models and orthophotos (tens of metres per pixel)", DatasetCategory.elevation,
                 ("terrain model", "stereo", "orthophoto", "regional terrain", "dtm", "topograph")),
    CatalogEntry("THEMIS thermal", "ODY", "THEMIS", "IRPBT2", "THEMIS projected infrared brightness temperature",
                 "surface temperature in thermal infrared images", DatasetCategory.thermal,
                 ("thermal", "temperature", "heat", "warm", "cold", "night", "day-night", "thermophysical", "infrared")),
    CatalogEntry("TES thermal inertia", "MGS", "TES", "TIMAP", "TES thermal inertia map",
                 "how fast the surface heats and cools (dust, sand, rock, bedrock)", DatasetCategory.thermal,
                 ("thermal inertia", "inertia", "sand", "dust", "bedrock", "loose material", "regolith")),
    CatalogEntry("SHARAD radar", "MRO", "SHARAD", "RDR", "SHARAD radar sounder profiles",
                 "subsurface layering and ice from radar echoes", DatasetCategory.geology,
                 ("subsurface", "radar", "buried", "ice", "layering", "sounder", "underground", "groundwater")),
)


def _fallback_resolve(text: str) -> str | None:
    t = text.lower()
    if re.search(r"hydrated|clay|phyllosilicate|mineral", t):
        return "hydrated_minerals"
    if re.search(r"vantage|high ground|high point", t):
        return "high_vantage_points"
    if re.search(r"\bflat\b|safe site|landing", t):
        return "flat_safe_sites"
    return None


def resolve_supported_id(text: str) -> str | None:
    """The id of the supported objective these words mean, or None. Uses the registry when it exists."""
    if _registry_resolve is not None:
        found = _registry_resolve(text)
        if found is None or isinstance(found, str):
            return found
        return getattr(found, "id", None)
    return _fallback_resolve(text)


def _default_fetch(url: str) -> dict[str, Any]:
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(QUERY_TIMEOUT_S, connect=5.0)) as client:
        return get_json(url, retries=1, client=client)


def _entry_for_supported(objective_id: str) -> str:
    return "CRISM" if objective_id == "hydrated_minerals" else "MOLA"


def match_entries(text: str, supported_id: str | None) -> list[CatalogEntry]:
    t = text.lower()
    scored = [(sum(1 for k in e.keywords if k in t), i, e) for i, e in enumerate(CATALOG)]
    hits = [(s, i, e) for s, i, e in scored if s > 0]
    hits.sort(key=lambda x: (-x[0], x[1]))
    chosen = [e for _, _, e in hits[:5]]
    if supported_id:                                  # a supported objective always brings the data it is computed from
        needed = _entry_for_supported(supported_id)
        if all(e.instrument != needed for e in chosen):
            chosen.append(next(e for e in CATALOG if e.instrument == needed))
    return chosen


def _query(entry: CatalogEntry, bounds: BoundingBox, fetch_json: FetchJson) -> tuple[int, float, list[str]]:
    """(product count, covered percent of the box by the union of their footprints, example ids), or raises."""
    url = build_product_query(bounds, ihid=entry.ihid, iid=entry.iid, pt=entry.pt, results="mp", limit=QUERY_LIMIT)
    records = parse_product_results(fetch_json(url), category=entry.category, aoi=bounds)
    if not records:
        return 0, 0.0, []
    selection = select_products(bounds, records, max_per_category=len(records))
    covered = round(100.0 * selection.categories[0].covered_fraction, 1) if selection.categories else 0.0
    ranked = sorted(records, key=lambda r: (-r.coverage.percent_of_aoi, r.product_id))
    return len(records), covered, [r.product_id for r in ranked[:3]]


def check_availability(objective: str, bounds: BoundingBox, *, fetch_json: FetchJson = _default_fetch, max_area_km2: float = 2500.0) -> AvailabilityResult:
    area_km2 = bounds_area_m2(bounds) / 1e6
    if area_km2 > max_area_km2:
        raise AreaTooLarge(f"the area is {area_km2:.0f} km2; the limit for one check is {max_area_km2:.0f} km2")
    supported_id = resolve_supported_id(objective)
    entries = match_entries(objective, supported_id)
    if not entries:
        return AvailabilityResult(objective=objective, matched_objective_id=None, supported=False,
                                  message="I don't know which NASA instrument measures that, so I cannot check whether data exists.")

    outcomes: dict[str, tuple[int, float, list[str]] | Exception] = {}

    def run(entry: CatalogEntry) -> None:
        try:
            outcomes[entry.instrument] = _query(entry, bounds, fetch_json)
        except (HttpFetchError, OdeError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            outcomes[entry.instrument] = exc

    with ThreadPoolExecutor(max_workers=min(len(entries), 5)) as pool:
        list(pool.map(run, entries))

    coverage: list[CoverageItem] = []
    warnings: list[str] = []
    failed: list[CatalogEntry] = []
    for e in entries:
        out = outcomes[e.instrument]
        if isinstance(out, Exception):
            failed.append(e)
            warnings.append(f"Could not query NASA's catalog for {e.label}: {type(out).__name__}.")
            continue
        count, percent, examples = out
        if e.analyzable:
            note = "This tool can analyse this product type."
        else:
            note = f"Data exists; this tool has no method to extract '{objective.strip()}' from it yet." if count else "No products listed for this area."
        if count >= QUERY_LIMIT:
            note += f" Only the first {QUERY_LIMIT} products were examined."
        coverage.append(CoverageItem(instrument=e.instrument, product_type=e.pt, label=e.label, measures=e.measures, covered_percent=percent,
                                     product_count=count, example_product_ids=examples, analyzable=e.analyzable, note=note))

    if len(failed) == len(entries):
        return AvailabilityResult(objective=objective, matched_objective_id=supported_id, supported=supported_id is not None,
                                  message="I could not reach NASA's catalog, so I cannot tell whether data exists for this area.",
                                  coverage=[], warnings=warnings)
    return AvailabilityResult(objective=objective, matched_objective_id=supported_id, supported=supported_id is not None,
                              message=_message(objective, supported_id, coverage, failed), coverage=coverage, warnings=warnings)


def _message(objective: str, supported_id: str | None, coverage: list[CoverageItem], failed: list[CatalogEntry]) -> str:
    usable = [c for c in coverage if c.product_count and (c.covered_percent or 0) > 0]
    analysable = [c for c in usable if c.analyzable]
    parts: list[str] = []
    if supported_id and analysable:
        best = max(analysable, key=lambda c: c.covered_percent or 0)
        parts.append(f"This objective is supported and NASA data covers {best.covered_percent:.0f}% of the area ({best.label}).")
    elif supported_id:
        needed = [c for c in coverage if c.analyzable]
        names = ", ".join(c.instrument for c in needed) or "the required instrument"
        parts.append(f"This objective is supported, but NASA's catalog lists no {names} products covering this area, so I cannot plan for it here.")
    else:
        others = [c for c in usable if not c.analyzable]
        if others:
            listing = "; ".join(f"{c.label}: {c.product_count} product{'s' if c.product_count != 1 else ''}, about {c.covered_percent:.0f}% of the area" for c in others)
            parts.append(f"NASA has data that could bear on this ({listing}), but this tool has no method to extract it yet, so I cannot plan for this objective.")
        elif analysable:
            parts.append("NASA data covers the area, but this tool has no method for this objective yet.")
        else:
            empty = ", ".join(c.instrument for c in coverage)
            parts.append(f"NASA's catalog lists no {empty} products covering this area, so I cannot plan for this objective here.")
    if failed:
        parts.append("I could not check " + ", ".join(e.instrument for e in failed) + " (catalog unreachable), so that data may still exist.")
    return " ".join(parts)
