"""Benchmark the analyzer's processing stages.

Offline (default): terrain derivatives, bundle write and verified reload, and the display package, on
synthetic elevation grids of increasing size (up to the ~1 million cell routing cap in the spec).
Peak memory is the Python/NumPy allocation peak from ``tracemalloc``.

With ``--real``: end-to-end analyses through the analysis service against the live USGS and PDS sources
(needs network access; times include downloads).

Run from ``backend/``:  python scripts/benchmark_analyzer.py [--real]
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analyzer.preprocessing.terrain_bundle import build_terrain_bundle, load_terrain_bundle  # noqa: E402
from app.analyzer.publishing.map_display import build_map_package  # noqa: E402
from app.connectors.usgs.mola import LAYOUT, MolaLayout, MolaWindow, dataset_record  # noqa: E402
from app.schemas import BoundingBox  # noqa: E402


def synthetic_window(n: int) -> MolaWindow:
    layout = MolaLayout(url="x", width=n + 2, height=n + 2, data_offset=0, deg_per_px=LAYOUT.deg_per_px, pixel_size_m=LAYOUT.pixel_size_m, file_size=0, etag="bench")
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:n + 2, 0:n + 2]
    z = (1000 * np.sin(xx / 40.0) + 800 * np.cos(yy / 55.0) + rng.normal(0, 3, (n + 2, n + 2))).astype(np.float32)
    d = layout.deg_per_px
    bounds = BoundingBox(west_deg_east=10.0, south_deg=20.0, east_deg_east=10.0 + (n + 2) * d, north_deg=20.0 + (n + 2) * d)
    return MolaWindow(elevation_m=z, valid=np.ones(z.shape, bool), bounds=bounds, row0=0, col0=0, pixel_size_y_m=layout.pixel_size_m,
                      pixel_size_x_m=layout.pixel_size_m * 0.94, bytes_fetched=0, provenance={})


def timed(fn):
    tracemalloc.start()
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return out, dt, peak / 1e6


def offline() -> list[str]:
    rows = ["| Cells | Derivatives + bundle write | Verified reload | Map package (257 px display) | Peak memory (build) |", "|---|---|---|---|---|"]
    for n in (100, 316, 1000):
        win = synthetic_window(n)
        with tempfile.TemporaryDirectory() as tmp:
            aid = uuid4()
            _, t_build, mem = timed(lambda: build_terrain_bundle(win, dataset_record(), aid, Path(tmp), generated_at=datetime(2026, 11, 14, tzinfo=timezone.utc)))
            (manifest, arrays), t_load, _ = timed(lambda: load_terrain_bundle(Path(tmp) / str(aid) / "terrain.manifest.json"))
            _, t_pkg, _ = timed(lambda: build_map_package(manifest, arrays, lambda k: "http://x"))
        rows.append(f"| {n * n:,} ({n} x {n}) | {t_build:.2f} s | {t_load:.2f} s | {t_pkg:.2f} s | {mem:.0f} MB |")
    return rows


def real() -> list[str]:
    from app.analyzer.orchestration.pipeline import AnalyzerDeps
    from app.analyzer.orchestration.service import AnalysisService
    from app.analyzer.science.pipeline import ScienceDeps
    from app.connectors.common.http import get_json, get_text
    from app.connectors.usgs.mola import http_range_fetcher
    from app.schemas import CreateAnalysisRequest, RegionOfInterest

    cases = [("small, terrain only", (77.40, 18.40, 77.45, 18.45), "terrain overview"),
             ("~1,900 km2, terrain only", (77.00, 18.10, 77.80, 18.80), "terrain overview"),
             ("~600 km2, terrain + CRISM", (77.30, 18.20, 77.65, 18.50), "find hydrated minerals")]
    rows = ["| Case | Cells | Wall time | Bytes read (MOLA) | Targets |", "|---|---|---|---|---|"]
    for name, (w, s, e, n), objective in cases:
        with tempfile.TemporaryDirectory() as tmp:
            svc = AnalysisService(AnalyzerDeps(fetch_range=http_range_fetcher(), out_dir=Path(tmp), science=ScienceDeps(
                fetch_json=lambda u: get_json(u, retries=3), fetch_text=lambda u: get_text(u, retries=3),
                range_fetcher_for=lambda u: http_range_fetcher(u, timeout_s=180.0, retries=3))))
            req = CreateAnalysisRequest(mission_id=uuid4(), objective=objective, roi=RegionOfInterest(
                name=name, bounds=BoundingBox(west_deg_east=w, south_deg=s, east_deg_east=e, north_deg=n), analysis_margin_m=0))
            t0 = time.perf_counter()
            job = svc.submit(req)
            svc.wait_idle()
            dt = time.perf_counter() - t0
            res = svc.get_result(job.id)
            if res is None:
                rows.append(f"| {name} | - | {dt:.1f} s | - | failed: {svc.get_job(job.id).error_code} |")
                continue
            terrain = svc.load_terrain(job.id)
            cells = terrain[0].shape[0] * terrain[0].shape[1]
            rows.append(f"| {name} | {cells:,} | {dt:.1f} s | {(terrain[0].shape[0] + 2) * LAYOUT.row_bytes / 1e6:.1f} MB | {len(res.science_targets)} |")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args()
    print(f"Python {platform.python_version()}, numpy {np.__version__}, {platform.system()} {platform.release()}, {os.cpu_count()} logical CPUs\n")
    print("Offline (synthetic grids)\n")
    print("\n".join(offline()))
    if args.real:
        print("\nLive sources\n")
        print("\n".join(real()))
