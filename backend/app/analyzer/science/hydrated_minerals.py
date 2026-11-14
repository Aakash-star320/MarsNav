"""Hydrated hydroxylated-mineral candidates from CRISM summary parameters.

What the documentation supports (PDS labels of the MTRDR browse product "PHY", see
``crism_parameters.py``): ``D2300`` responds to Mg/Fe-OH bearing minerals, ``D2200`` to Al/Si-OH bearing
minerals, and ``BD1900R2`` to bound water; the label says such surfaces "may appear red, or magenta when
hydrated" (D2300 + BD1900R2) and "green, or cyan when hydrated" (D2200 + BD1900R2).

What this module adds (a heuristic, not a published detection criterion, and reported as such):

* normalised strength ``n_p = clip(value_p / stretch_p, 0, 1)`` where ``stretch_p`` is the parameter value
  at which the PDS browse product saturates;
* evidence ``e = min(max(n_D2300, n_D2200), n_BD1900R2)``: an OH absorption AND a hydration absorption
  must both be strong, which is the "magenta or cyan" condition of the label;
* a pixel is a candidate when ``e >= threshold_fraction`` (default 0.5, half of the display stretch);
* connected candidate pixels (8-neighbourhood) form a group; groups smaller than ``min_pixels`` are
  discarded as noise;
* rank score ``0.7 * mean(e) + 0.3 * min(1, pixels / 400)``, with the components reported.

Outputs are candidate spectral signatures. They are not identified minerals, not calibrated probabilities,
and say nothing about places where no data exist.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .crism_parameters import PHY

OH_BANDS = ("D2300", "D2200")
HYDRATION_BAND = "BD1900R2"
REQUIRED_BANDS = (*OH_BANDS, HYDRATION_BAND)
RANK_WEIGHTS = (0.7, 0.3)
RANK_SIZE_REFERENCE_PIXELS = 400
MEDIUM_CONFIDENCE_PIXELS, MEDIUM_CONFIDENCE_MEAN = 100, 0.75


@dataclass(frozen=True)
class DetectionConfig:
    threshold_fraction: float = 0.5
    min_pixels: int = 25
    max_candidates: int = 12

    def __post_init__(self) -> None:
        if not 0 < self.threshold_fraction <= 1:
            raise ValueError("threshold_fraction must be in (0, 1]")
        if self.min_pixels < 1 or self.max_candidates < 1:
            raise ValueError("min_pixels and max_candidates must be at least 1")


@dataclass(frozen=True)
class Candidate:
    row: float                    # evidence-weighted centroid, pixel-centre coordinates in the window
    col: float
    pixels: int
    mean_evidence: float
    max_evidence: float
    rank_score: float
    confidence: str               # "low" | "medium": strength and extent only, never mineral identity
    mean_values: dict[str, float]         # raw summary parameter means (band-depth / index, dimensionless)
    mean_normalised: dict[str, float]
    bbox: tuple[int, int, int, int]       # row0, row1, col0, col1 (half-open) in the window
    dominant_oh: str              # which OH parameter is stronger on average: "D2300" or "D2200"


def normalise(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    missing = [b for b in REQUIRED_BANDS if b not in bands]
    if missing:
        raise ValueError(f"missing summary parameters: {missing}")
    shape = bands[REQUIRED_BANDS[0]].shape
    if any(bands[b].shape != shape for b in REQUIRED_BANDS):
        raise ValueError("summary parameter windows must share one shape")
    return {b: np.clip(bands[b] / PHY.stretch_max(b), 0.0, 1.0) for b in REQUIRED_BANDS}


def evidence_map(bands: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(evidence in [0, 1], valid mask). A pixel is valid only where all three parameters are finite."""
    n = normalise(bands)
    valid = np.logical_and.reduce([np.isfinite(bands[b]) for b in REQUIRED_BANDS])
    e = np.minimum(np.fmax(n["D2300"], n["D2200"]), n[HYDRATION_BAND])
    return np.where(valid, e, np.nan), valid


def detect(bands: dict[str, np.ndarray], config: DetectionConfig = DetectionConfig()) -> list[Candidate]:
    e, valid = evidence_map(bands)
    mask = valid & (e >= config.threshold_fraction)
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    n = normalise(bands)
    out: list[Candidate] = []
    for i in range(1, count + 1):
        sel = labels == i
        pixels = int(sel.sum())
        if pixels < config.min_pixels:
            continue
        rows, cols = np.nonzero(sel)
        w = e[sel]
        mean_e = float(w.mean())
        score = RANK_WEIGHTS[0] * mean_e + RANK_WEIGHTS[1] * min(1.0, pixels / RANK_SIZE_REFERENCE_PIXELS)
        mean_n = {b: float(n[b][sel].mean()) for b in REQUIRED_BANDS}
        out.append(Candidate(
            row=float((rows * w).sum() / w.sum()) + 0.5, col=float((cols * w).sum() / w.sum()) + 0.5,
            pixels=pixels, mean_evidence=mean_e, max_evidence=float(w.max()), rank_score=float(score),
            confidence="medium" if pixels >= MEDIUM_CONFIDENCE_PIXELS and mean_e >= MEDIUM_CONFIDENCE_MEAN else "low",
            mean_values={b: float(bands[b][sel].mean()) for b in REQUIRED_BANDS}, mean_normalised=mean_n,
            bbox=(int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1),
            dominant_oh=max(OH_BANDS, key=lambda b: mean_n[b]),
        ))
    out.sort(key=lambda c: (-c.rank_score, round(c.row, 3), round(c.col, 3)))      # deterministic order
    return out[: config.max_candidates]
