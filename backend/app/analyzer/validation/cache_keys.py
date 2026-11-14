"""Stable cache keys for analyzer artifacts.

The analyzer supplies keys and the cache service stores data. Keys use canonical JSON (sorted keys,
fixed float formatting) so the same inputs always hash identically across runs and processes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas import BoundingBox


def _canonical(value: Any) -> Any:
    if isinstance(value, float):
        return format(round(value, 9), ".9f")
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def stable_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_product_key(source: str, product_id: str, version_or_checksum: str | None) -> str:
    return stable_hash({"kind": "raw", "source": source, "product_id": product_id, "version": version_or_checksum or ""})


def processed_region_key(
    bounds: BoundingBox, crs_wkt: str, product_versions: dict[str, str], algorithm_version: str,
    resolution_m: float, parameters: dict[str, Any], categories: list[str],
) -> str:
    return stable_hash({
        "kind": "processed", "bounds": bounds.model_dump(), "crs": crs_wkt, "products": product_versions,
        "algorithm": algorithm_version, "resolution_m": resolution_m, "parameters": parameters,
        "categories": sorted(categories),
    })


def analysis_result_key(processed_key: str, objective: str, configuration: dict[str, Any]) -> str:
    return stable_hash({"kind": "analysis", "processed": processed_key, "objective": objective, "configuration": configuration})
