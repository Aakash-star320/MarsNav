"""Persist and render the CRISM evidence raster so the map can show where the candidate rule is strong.

The raster stays on the CRISM observation's own regular longitude/latitude grid (an equirectangular
product), so it is draped by its geographic bounds without resampling. Values are the normalised
evidence ``e`` in [0, 1] (see docs/SCIENCE_CRISM.md); NaN means no data and is transparent.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from uuid import UUID, uuid5

from app.schemas import BoundingBox, ProcessedLayer
from app.schemas.map_display import MapLayerEntry

from .map_display import colorize, png_bytes

FADE_BELOW = 0.25           # evidence under this is fully transparent so only meaningful areas show
COLORS = ["#4b2a7a", "#ff5cf4"]


@dataclass(frozen=True)
class ScienceLayer:
    values: np.ndarray          # float32 (rows, cols), NaN where there is no data
    bounds: BoundingBox
    product_id: str
    pixel_m: float
    sha256: str = ""


def _atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save_science_layer(folder: Path, layer: ScienceLayer) -> None:
    import io
    folder.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    np.savez_compressed(buf, values=layer.values.astype(np.float32))
    data = buf.getvalue()
    _atomic(folder / "science.npz", data)
    meta = {"bounds": layer.bounds.model_dump(), "product_id": layer.product_id, "pixel_m": layer.pixel_m, "sha256": hashlib.sha256(data).hexdigest()}
    _atomic(folder / "science.json", json.dumps(meta).encode("utf-8"))      # written last: its presence means the array is complete


def load_science_layer(folder: Path) -> ScienceLayer | None:
    meta_path, npz_path = folder / "science.json", folder / "science.npz"
    if not (meta_path.is_file() and npz_path.is_file()):
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    data = npz_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != meta["sha256"]:
        return None                                                          # corrupt: treated as absent, never half-shown
    import io
    with np.load(io.BytesIO(data)) as z:
        values = z["values"]
    return ScienceLayer(values=values, bounds=BoundingBox(**meta["bounds"]), product_id=meta["product_id"], pixel_m=float(meta["pixel_m"]), sha256=meta["sha256"])


def render_science_png(layer: ScienceLayer) -> bytes:
    v = layer.values
    rgba = colorize(v, np.isfinite(v), 0.0, 1.0, COLORS)
    rgba[..., 3] = np.where(np.isfinite(v) & (v >= FADE_BELOW), np.clip(110 + 145 * (v - FADE_BELOW) / (1 - FADE_BELOW), 0, 255), 0).astype(np.uint8)
    return png_bytes(rgba)


def science_map_entry(layer: ScienceLayer, url: str, analysis_id: UUID, dataset_ids: list[UUID]) -> MapLayerEntry:
    finite = np.isfinite(layer.values)
    pct = 100.0 * float(finite.mean()) if finite.size else 0.0
    coverage = "available" if pct >= 99.99 else "partial"
    return MapLayerEntry(
        layer=ProcessedLayer(
            id=uuid5(analysis_id, "map-science"), kind="science", uri=url, bounds=layer.bounds, resolution_m_per_px=layer.pixel_m,
            valid_percent=pct, units="fraction of the PDS browse stretch", dataset_ids=dataset_ids, availability=coverage,
            limitations=["Heuristic evidence screen of CRISM summary parameters, not identified minerals.",
                         "Missing data are transparent; no data is not evidence of absence."],
            style_hint={"shown_where_at_least": FADE_BELOW, "observation": layer.product_id},
        ),
        source=f"NASA PDS CRISM MTRDR {layer.product_id}", synthetic=False, coverage=coverage, colors=COLORS,
        legend=(f"CRISM hydrated-mineral evidence, 0 to 1 of the PDS browse stretch ({layer.product_id}); shown where at least {FADE_BELOW:g}; "
                "heuristic, not identified minerals; missing data is transparent"),
    )
