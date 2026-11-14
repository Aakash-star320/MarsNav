"""Deterministic greedy product selection per measurement category.

Coverage is evaluated on a fixed grid over the AOI using each dataset's footprint box from the shared
contract (``DatasetCoverage.footprint``); exact polygon footprints are not representable there, so the
result says so. Detailed products are chosen first (finest native resolution that adds at least MIN_GAIN of
new coverage); the last slot per category goes to the product with the largest remaining coverage,
so a reliable lower-resolution fallback can fill gaps. Ties break on product id, so output is
reproducible. Missing observations stay unknown: coverage is never filled
from a different measurement category.
"""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from app.schemas import BoundingBox, CoverageStatus, DatasetCategory, DatasetRecord

GRID = 100            # AOI is sampled on a GRID x GRID raster for coverage arithmetic
MIN_GAIN = 0.01       # a product must add at least 1% of the AOI to be selected


class RejectedProduct(BaseModel):
    dataset: DatasetRecord
    reason: str


class CategorySelection(BaseModel):
    category: DatasetCategory
    selected: list[DatasetRecord] = Field(default_factory=list)
    covered_fraction: float = 0.0
    rejected: list[RejectedProduct] = Field(default_factory=list)


class SelectionResult(BaseModel):
    categories: list[CategorySelection]
    notes: list[str] = Field(default_factory=lambda: ["Coverage uses footprint boxes, not exact footprint polygons."])


def _mask(aoi: BoundingBox, fp: BoundingBox) -> np.ndarray:
    xs = aoi.west_deg_east + (np.arange(GRID) + 0.5) / GRID * (aoi.east_deg_east - aoi.west_deg_east)
    ys = aoi.south_deg + (np.arange(GRID) + 0.5) / GRID * (aoi.north_deg - aoi.south_deg)
    in_x = (xs >= fp.west_deg_east) & (xs <= fp.east_deg_east)
    in_y = (ys >= fp.south_deg) & (ys <= fp.north_deg)
    return np.outer(in_y, in_x)


def _unusable(d: DatasetRecord) -> str | None:
    if d.coverage.status in (CoverageStatus.unavailable, CoverageStatus.unknown):
        return f"coverage status is {d.coverage.status.value}"
    if d.coverage.footprint is None:
        return "no footprint available"
    return None


def select_products(aoi: BoundingBox, candidates: list[DatasetRecord], max_per_category: int = 3) -> SelectionResult:
    by_cat: dict[DatasetCategory, list[DatasetRecord]] = {}
    for d in candidates:
        by_cat.setdefault(d.category, []).append(d)
    out: list[CategorySelection] = []
    for cat in sorted(by_cat, key=lambda c: c.value):
        sel = CategorySelection(category=cat)
        seen: set[tuple[str, str, str | None]] = set()
        pool: list[tuple[DatasetRecord, np.ndarray]] = []
        for d in sorted(by_cat[cat], key=lambda d: (d.source, d.product_id, d.version or "")):
            key = (d.source, d.product_id, d.version)
            if key in seen:
                sel.rejected.append(RejectedProduct(dataset=d, reason="duplicate product id and version"))
                continue
            seen.add(key)
            bad = _unusable(d)
            if bad:
                sel.rejected.append(RejectedProduct(dataset=d, reason=bad))
                continue
            m = _mask(aoi, d.coverage.footprint)  # type: ignore[arg-type]
            if not m.any():
                sel.rejected.append(RejectedProduct(dataset=d, reason="footprint does not overlap the AOI"))
                continue
            pool.append((d, m))
        covered = np.zeros((GRID, GRID), dtype=bool)
        while pool and len(sel.selected) < max_per_category:
            scored = [(float((m & ~covered).mean()), d.resolution_m_per_px or float("inf"), d.product_id, i)
                      for i, (d, m) in enumerate(pool)]
            scored = [t for t in scored if t[0] >= MIN_GAIN] or scored
            if len(sel.selected) == max_per_category - 1:      # last slot: widest remaining coverage
                scored.sort(key=lambda t: (-t[0], t[1], t[2]))
            else:                                              # otherwise: finest resolution first
                scored.sort(key=lambda t: (t[1], -t[0], t[2]))
            gain, _, _, idx = scored[0]
            if gain < MIN_GAIN:
                break
            d, m = pool.pop(idx)
            sel.selected.append(d)
            covered |= m
        for d, _ in pool:
            sel.rejected.append(RejectedProduct(dataset=d, reason=f"adds less than {MIN_GAIN:.0%} new coverage or per-category limit reached"))
        sel.covered_fraction = float(covered.mean())
        out.append(sel)
    return SelectionResult(categories=out)
