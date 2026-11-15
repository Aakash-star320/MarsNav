"""The registry of science objectives the analyzer can really answer.

Each entry says what the objective is called, which words identify it, which data it uses and what its limits are.
An objective that is not here is not interpreted: the analysis returns terrain statistics only and says so.

``hydrated_minerals`` uses the CRISM path in ``science/pipeline.py``. The two terrain objectives use only the elevation
product the analyzer already reads (``science/terrain_objectives.py``), so they need no extra download.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HYDRATED = "hydrated_minerals"
FLAT_SITES = "flat_safe_sites"
VANTAGE = "high_vantage_points"
LOWEST = "lowest_ground"
CLIFFS = "steep_cliffs"
RIDGES = "ridges"
CRATERS = "craters"
TERRAIN_OBJECTIVES = (FLAT_SITES, VANTAGE, LOWEST, CLIFFS, RIDGES, CRATERS)


@dataclass(frozen=True)
class Objective:
    id: str
    label: str
    description: str
    keywords: tuple[str, ...]      # matched at the start of a word, case-insensitively ("mineral" also matches "minerals")
    data_used: tuple[str, ...]
    limitation: str
    kind: str                      # "spectral" or "terrain"


REGISTRY: tuple[Objective, ...] = (
    Objective(
        id=HYDRATED, label="Hydrated minerals", kind="spectral",
        description="Sites where CRISM summary parameters suggest hydrated hydroxylated minerals (clays and similar), which can record past water.",
        keywords=("hydrated", "mineral", "clay", "phyllosilicate", "smectite", "science"),
        data_used=("MRO CRISM MTRDR summary parameters (found through the ODE catalog)", "USGS MOLA 463 m elevation"),
        limitation="A heuristic screen of three summary parameters, not an identified mineral; no coverage is not evidence of absence.",
    ),
    Objective(
        id=FLAT_SITES, label="Flat safe sites", kind="terrain",
        description="Connected patches of gentle, smooth ground where a crew could stage equipment or stop safely.",
        keywords=("flat", "safe site", "safe place", "safe landing", "landing site", "level ground", "smooth ground", "staging", "camp site", "campsite"),
        data_used=("USGS MOLA 463 m elevation, with slope and roughness derived from it",),
        limitation="463 m cells: a site is a patch of cells, not a surveyed landing site; rocks and small craters cannot be seen.",
    ),
    Objective(
        id=VANTAGE, label="High vantage points", kind="terrain",
        description="Local high ground that stands clear of its surroundings, for overlooking the area, line of sight and communications.",
        keywords=("vantage", "high ground", "highest point", "high point", "summit", "peak", "lookout", "overlook", "hilltop", "viewpoint"),
        data_used=("USGS MOLA 463 m elevation, with slope derived from it",),
        limitation="Heights come from a 463 m global model: a point is the highest cell of a rise, and line of sight is not computed.",
    ),
    Objective(
        id=LOWEST, label="Lowest ground", kind="terrain",
        description="Local low points and basin floors: ground that sits clearly below its surroundings, where material collects.",
        keywords=("lowest", "low point", "low ground", "basin", "depression", "lowland", "lowlands", "bottom"),
        data_used=("USGS MOLA 463 m elevation, with slope derived from it",),
        limitation="Depths come from a 463 m global model: only basins several cells wide can be seen.",
    ),
    Objective(
        id=CLIFFS, label="Steep cliffs", kind="terrain",
        description="Connected stretches of steep ground such as scarps and escarpments, with the height they drop.",
        keywords=("cliff", "cliffs", "scarp", "scarps", "escarpment", "steep terrain", "steep ground", "drop off", "drop-off"),
        data_used=("USGS MOLA 463 m elevation, with slope derived from it",),
        limitation="Slopes are averaged over 463 m cells, so only large, long steep faces appear.",
    ),
    Objective(
        id=RIDGES, label="Ridges", kind="terrain",
        description="Long, narrow rises that stand above the ground around them.",
        keywords=("ridge", "ridges", "ridgeline", "crest", "crests"),
        data_used=("USGS MOLA 463 m elevation",),
        limitation="Found as raised, elongated areas of the 463 m grid, so narrow ridges are missed.",
    ),
    Objective(
        id=CRATERS, label="Craters", kind="terrain",
        description="Round, bowl-shaped depressions with higher ground around them.",
        keywords=("crater", "craters", "impact basin", "bowl", "rim", "rims"),
        data_used=("USGS MOLA 463 m elevation",),
        limitation="At 463 m per cell only large craters, several kilometres across, can be found.",
    ),
)
_BY_ID = {o.id: o for o in REGISTRY}


def list_objectives() -> tuple[Objective, ...]:
    return REGISTRY


def get_objective(objective_id: str) -> Objective | None:
    return _BY_ID.get(objective_id)


def supported_labels() -> str:
    return ", ".join(o.label for o in REGISTRY)


def resolve_objective(text: str) -> str | None:
    """The id of the supported objective that ``text`` names, or None (terrain statistics only).

    An exact id or label wins. Otherwise the objective with the most distinct keyword matches wins, then the one with
    the longest matched keyword, then registry order, so "flat safe sites for science" is a terrain objective even
    though "science" alone would suggest hydrated minerals.
    """
    t = (text or "").strip().lower()
    if not t:
        return None
    for o in REGISTRY:
        if t in (o.id, o.label.lower(), o.id.replace("_", " ")):
            return o.id
    best: tuple[int, int, int] | None = None
    best_id: str | None = None
    for order, o in enumerate(REGISTRY):
        hits = [k for k in o.keywords if re.search(r"\b" + re.escape(k), t)]
        if not hits:
            continue
        score = (len(hits), max(len(k) for k in hits), -order)
        if best is None or score > best:
            best, best_id = score, o.id
    return best_id
