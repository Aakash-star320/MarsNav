"""Analysis endpoints (analyzer-owned): create a job, poll it, fetch the result."""
from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.analyzer.publishing.map_display import build_map_package, render_layer_png
from app.connectors.usgs.mola import http_range_fetcher
from app.core.config import settings
from app.schemas import AnalysisJob, CreateAnalysisRequest, JobStage, RegionalAnalysisResult
from app.schemas.map_display import MapPackage

router = APIRouter()


@lru_cache
def get_service() -> AnalysisService:
    deps = AnalyzerDeps(
        fetch_range=http_range_fetcher(), out_dir=settings.data_root / "derived" / "analyses",
        max_area_km2=settings.analyzer_max_area_km2, max_download_bytes=settings.analyzer_max_download_bytes,
    )
    return AnalysisService(deps)


@router.post("/analyses", response_model=AnalysisJob, status_code=status.HTTP_202_ACCEPTED)
def create_analysis(req: CreateAnalysisRequest, service: AnalysisService = Depends(get_service)) -> AnalysisJob:
    return service.submit(req)


@router.get("/analyses/{analysis_id}", response_model=AnalysisJob)
def get_analysis(analysis_id: UUID, service: AnalysisService = Depends(get_service)) -> AnalysisJob:
    job = service.get_job(analysis_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    return job


@router.get("/analyses/{analysis_id}/result", response_model=RegionalAnalysisResult)
def analysis_result(analysis_id: UUID, service: AnalysisService = Depends(get_service)) -> RegionalAnalysisResult:
    job = service.get_job(analysis_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "analysis not found")
    if job.stage != JobStage.completed:
        detail = {"stage": job.stage.value, "error_code": job.error_code, "message": job.message}
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
    result = service.get_result(analysis_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "result artifact is missing")
    return result


LayerKind = Literal["elevation", "slope", "roughness"]
_ARRAY = {"elevation": "elevation_m", "slope": "slope_deg", "roughness": "roughness_m"}


@router.get("/analyses/{analysis_id}/map", response_model=MapPackage)
def analysis_map(analysis_id: UUID, request: Request, service: AnalysisService = Depends(get_service)) -> MapPackage:
    """Map-ready layers (image URLs) and a display DEM for a completed analysis."""
    terrain = service.load_terrain(analysis_id)
    if terrain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no completed analysis terrain for this id")
    manifest, arrays = terrain
    return build_map_package(
        manifest, arrays, lambda kind: str(request.url_for("analysis_layer_png", analysis_id=analysis_id, kind=kind)),
    )


@router.get("/analyses/{analysis_id}/layers/{kind}.png", name="analysis_layer_png", response_class=Response)
def analysis_layer_png(analysis_id: UUID, kind: LayerKind, service: AnalysisService = Depends(get_service)) -> Response:
    terrain = service.load_terrain(analysis_id)
    if terrain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no completed analysis terrain for this id")
    manifest, arrays = terrain
    return Response(
        render_layer_png(arrays, _ARRAY[kind]), media_type="image/png",
        headers={"ETag": f'"{manifest.sha256[:16]}-{kind}"', "Cache-Control": "private, max-age=3600"},
    )
