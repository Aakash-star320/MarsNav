"""Analysis endpoints (analyzer-owned): create a job, poll it, fetch the result."""
from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.connectors.usgs.mola import http_range_fetcher
from app.core.config import settings
from app.schemas import AnalysisJob, CreateAnalysisRequest, JobStage, RegionalAnalysisResult

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
