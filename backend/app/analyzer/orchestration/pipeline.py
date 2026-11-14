"""Region-analysis pipeline: plan -> discover -> select -> acquire -> derive terrain -> publish.

Stages are plain functions with injected dependencies, so each is testable and the acquisition step can
be replaced by the cache/download service. Progress is reported only at real stage transitions.
Currently supported: terrain analysis from the global MOLA DEM. Science objectives are not supported
yet; the result says so explicitly instead of producing targets.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import UUID

from app.analyzer.discovery.mars_geometry import GeometryError, pad_bounds
from app.analyzer.discovery.region_planner import RegionPlanningError, plan_analyze_region
from app.analyzer.preprocessing.terrain_bundle import build_terrain_bundle
from app.analyzer.publishing.science_layer import ScienceLayer, save_science_layer
from app.analyzer.science.pipeline import ScienceDeps, ScienceOutcome, run_hydrated_minerals, wants_hydrated_minerals
from app.analyzer.selection.selector import select_products
from app.connectors.usgs import mola
from app.schemas import (
    CreateAnalysisRequest,
    DatasetCategory,
    DatasetRecord,
    JobStage,
    RegionalAnalysisResult,
)

ANALYSIS_VERSION = "analysis/1"
Progress = Callable[[JobStage, int, str], None]


class AnalysisError(RuntimeError):
    """Pipeline failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AnalyzerDeps:
    fetch_range: mola.RangeFetcher
    out_dir: Path
    max_area_km2: float = 2500.0
    max_download_bytes: int = 64 * 1024 * 1024
    mola_layout: mola.MolaLayout = mola.LAYOUT
    catalog: Callable[[], list[DatasetRecord]] | None = None     # injectable product discovery
    science: ScienceDeps | None = None                           # CRISM access; without it no science stage runs


def _drop(pool: ThreadPoolExecutor | None) -> None:
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def run_region_analysis(
    analysis_id: UUID, request: CreateAnalysisRequest, deps: AnalyzerDeps, progress: Progress, now: datetime,
) -> RegionalAnalysisResult:
    warnings: list[str] = []
    science_pool: ThreadPoolExecutor | None = None
    science_future: Future[ScienceOutcome] | None = None
    try:
        progress(JobStage.discovery, 10, "Planning the analysis region and discovering terrain products")
        bounds = pad_bounds(request.roi.bounds, request.roi.analysis_margin_m)
        plan = plan_analyze_region(bounds, max_area_km2=deps.max_area_km2)
        if deps.science is not None and wants_hydrated_minerals(request.objective):
            # CRISM discovery and reads only need the planned bounds, so they run while the elevation is read.
            science_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="science")
            science_future = science_pool.submit(run_hydrated_minerals, plan.bounds, deps.science)
        candidates = deps.catalog() if deps.catalog else [mola.dataset_record(deps.mola_layout)]

        progress(JobStage.selection, 25, "Selecting products for the region")
        selection = select_products(plan.bounds, candidates)
        elevation = next((c for c in selection.categories if c.category == DatasetCategory.elevation), None)
        if elevation is None or not elevation.selected:
            raise AnalysisError("no_elevation_data", "no compatible elevation product covers the region; terrain analysis is unavailable")
        dataset = elevation.selected[0]
        if dataset.product_id != mola.PRODUCT_ID:
            raise AnalysisError("unsupported_product", f"no reader is implemented for {dataset.product_id}")
        if elevation.covered_fraction < 1.0:
            warnings.append(f"Elevation coverage is {elevation.covered_fraction:.0%} of the region; uncovered cells stay unknown.")

        progress(JobStage.downloading, 40, "Reading the region's rows from the elevation product")
        window = mola.read_window(plan.bounds, deps.fetch_range, deps.mola_layout, max_bytes=deps.max_download_bytes)

        progress(JobStage.preprocessing, 60, f"Validating {window.elevation_m.shape[0]} x {window.elevation_m.shape[1]} cell window")
        if not window.valid.any():
            raise AnalysisError("all_nodata", "the elevation window contains no valid cells")

        progress(JobStage.terrain, 80, "Deriving slope and roughness and publishing the terrain bundle")
        bundle = build_terrain_bundle(window, dataset, analysis_id, deps.out_dir, generated_at=now)
    except RegionPlanningError as exc:
        _drop(science_pool)
        raise AnalysisError(exc.code, str(exc)) from exc
    except GeometryError as exc:
        _drop(science_pool)
        raise AnalysisError(exc.code, str(exc)) from exc
    except mola.MolaError as exc:
        _drop(science_pool)
        raise AnalysisError(f"elevation_{exc.code}", str(exc)) from exc
    except BaseException:
        _drop(science_pool)                      # cancellation or an unexpected error: do not wait for CRISM
        raise

    science = ScienceOutcome(attempted=False)
    if science_future is not None:
        try:
            progress(JobStage.science, 90, "Finishing the CRISM search and screening summary parameters")
            science = science_future.result()
        finally:
            _drop(science_pool)
        if science.evidence is not None:
            ev = science.evidence
            save_science_layer(deps.out_dir / str(analysis_id), ScienceLayer(values=ev.values, bounds=ev.bounds, product_id=ev.product_id, pixel_m=ev.pixel_m))
    warnings.append("Elevation comes from a coarse 463 m global product: suitable for broad planning, not astronaut-scale hazard detection.")
    if science.attempted and (science.targets or science.provenance or science.warnings):
        warnings.extend(science.warnings)
    else:
        warnings.append(f"Objective '{request.objective}' is not interpreted: it does not name a supported science objective (hydrated minerals), so no science targets are returned.")
    return RegionalAnalysisResult(
        id=analysis_id, mission_id=request.mission_id, roi=request.roi.model_copy(update={"local_projection": bundle.manifest.grid.crs_wkt}),
        projection_wkt=bundle.manifest.grid.crs_wkt, grid=bundle.manifest.grid, datasets=[dataset, *science.datasets], layers=bundle.layers,
        science_targets=science.targets, warnings=warnings,
        processing_provenance=[bundle.layers[0].provenance, *([science.provenance] if science.provenance else [])], analysis_version=ANALYSIS_VERSION,
    )
