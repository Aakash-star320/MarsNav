"""Typed assistant tools.

Every call is validated against a Pydantic argument model before anything runs. Results are copied
from the real services (analysis jobs, terrain statistics, dataset records); nothing here computes
or invents coordinates or metrics, and no raster arrays are returned. Tools that belong to other
services (routing, navigation) are registered as unavailable and say so, instead of guessing.
"""
from __future__ import annotations

from typing import Any, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError

from app.analyzer.orchestration.service import AnalysisService
from app.analyzer.publishing.statistics import compute_statistics
from app.connectors.usgs import mola
from app.schemas import (
    AssistantToolCall,
    AssistantToolName,
    BoundingBox,
    CreateAnalysisRequest,
    JobStage,
    RegionOfInterest,
)


class AnalysisStartArgs(BaseModel):
    bounds: BoundingBox
    name: str = Field(default="Selected area", min_length=1, max_length=120)
    objective: str = Field(default="terrain overview", min_length=1, max_length=500)


class AnalysisIdArgs(BaseModel):
    analysis_id: UUID


class AnalysisResultArgs(AnalysisIdArgs):
    slope_limit_deg: float = Field(default=12.0, gt=0, le=45)


class TargetLookupArgs(AnalysisIdArgs):
    target_id: UUID | None = None


class DatasetStatusArgs(BaseModel):
    analysis_id: UUID | None = None


class ToolSpec(BaseModel):
    name: AssistantToolName
    description: str
    arguments_schema: dict[str, Any]
    available: bool = True


_ARGS: dict[AssistantToolName, type[BaseModel]] = {
    AssistantToolName.analysis_start: AnalysisStartArgs,
    AssistantToolName.analysis_status: AnalysisIdArgs,
    AssistantToolName.analysis_result: AnalysisResultArgs,
    AssistantToolName.target_lookup: TargetLookupArgs,
    AssistantToolName.dataset_status: DatasetStatusArgs,
}
_UNAVAILABLE = {AssistantToolName.route_create, AssistantToolName.route_replan, AssistantToolName.navigation_guide}
_DESCRIPTIONS = {
    AssistantToolName.analysis_start: "Start a terrain analysis for a longitude/latitude bounding box (planetocentric, east-positive).",
    AssistantToolName.analysis_status: "Get the stage, progress and any error of an analysis.",
    AssistantToolName.analysis_result: "Summarize a finished analysis: area, elevation, slope statistics, layers and warnings (no raster data).",
    AssistantToolName.target_lookup: "List science targets of a finished analysis, or one by id.",
    AssistantToolName.dataset_status: "Describe the datasets behind an analysis, or the available source catalog.",
    AssistantToolName.route_create: "Create a route (provided by the routing service).",
    AssistantToolName.route_replan: "Replan a route around blocked areas (provided by the routing service).",
    AssistantToolName.navigation_guide: "Give navigation guidance along a route (provided by the routing service).",
}


def tool_specs() -> list[ToolSpec]:
    """Tool descriptions and argument JSON schemas, for a language model's tool-calling interface."""
    specs = []
    for name in AssistantToolName:
        model = _ARGS.get(name)
        specs.append(ToolSpec(
            name=name, description=_DESCRIPTIONS[name], available=name not in _UNAVAILABLE,
            arguments_schema=model.model_json_schema() if model else {"type": "object", "properties": {}},
        ))
    return specs


class ToolExecutor:
    def __init__(self, service: AnalysisService, new_id: Callable[[], str] = lambda: uuid4().hex) -> None:
        self._svc = service
        self._new_id = new_id

    def execute(self, name: str, raw_arguments: dict[str, Any] | None, mission_id: UUID) -> AssistantToolCall:
        call_id = self._new_id()
        raw = dict(raw_arguments or {})
        try:
            tool = AssistantToolName(name)
        except ValueError as exc:
            raise UnknownToolError(f"'{name}' is not a supported tool") from exc
        if tool in _UNAVAILABLE:
            return self._done(call_id, tool, raw, "rejected", error=("not_available", "The routing service is not connected to the assistant yet, so routes cannot be created, replanned or guided."))
        try:
            args = _ARGS[tool].model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0]
            return self._done(call_id, tool, raw, "rejected", error=("invalid_arguments", f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"))
        try:
            return self._done(call_id, tool, args.model_dump(mode="json"), "completed", result=getattr(self, f"_{tool.value}")(args, mission_id))
        except ToolFailure as fail:
            return self._done(call_id, tool, args.model_dump(mode="json"), "failed", error=(fail.code, str(fail)))

    @staticmethod
    def _done(call_id, tool, arguments, status, result=None, error=None) -> AssistantToolCall:
        return AssistantToolCall(
            id=call_id, name=tool, arguments=arguments, status=status, result=result,
            error_code=error[0] if error else None, error_message=error[1] if error else None,
        )

    # -- tools ---------------------------------------------------------------------------------
    def _job(self, analysis_id: UUID):
        job = self._svc.get_job(analysis_id)
        if job is None:
            raise ToolFailure("not_found", f"analysis {analysis_id} does not exist")
        return job

    def _analysis_start(self, a: AnalysisStartArgs, mission_id: UUID) -> dict[str, Any]:
        job = self._svc.submit(CreateAnalysisRequest(
            mission_id=mission_id, objective=a.objective, roi=RegionOfInterest(name=a.name, bounds=a.bounds, analysis_margin_m=0)))
        return _job_dict(job)

    def _analysis_status(self, a: AnalysisIdArgs, mission_id: UUID) -> dict[str, Any]:
        return _job_dict(self._job(a.analysis_id))

    def _completed(self, analysis_id: UUID):
        job = self._job(analysis_id)
        if job.stage != JobStage.completed:
            raise ToolFailure("not_ready", f"analysis {analysis_id} is {job.stage.value}, not completed" + (f" ({job.error_code})" if job.error_code else ""))
        result = self._svc.get_result(analysis_id)
        if result is None:
            raise ToolFailure("unavailable", "the analysis result artifact is missing")
        return result

    def _analysis_result(self, a: AnalysisResultArgs, mission_id: UUID) -> dict[str, Any]:
        result = self._completed(a.analysis_id)
        terrain = self._svc.load_terrain(a.analysis_id)
        if terrain is None:
            raise ToolFailure("unavailable", "the terrain arrays are missing or failed verification")
        stats = compute_statistics(terrain[0], terrain[1], a.slope_limit_deg, len(result.science_targets))
        return {
            "analysis_id": str(result.id), "analysis_version": result.analysis_version,
            "bounds": result.layers[0].bounds.model_dump(mode="json") if result.layers else None,
            "layers": {layer.kind: str(layer.id) for layer in result.layers},
            "statistics": stats.model_dump(mode="json"), "warnings": list(result.warnings),
            "sources": [{"product_id": d.product_id, "version": d.version, "resolution_m_per_px": d.resolution_m_per_px,
                         "provenance_url": str(d.provenance_url) if d.provenance_url else None} for d in result.datasets],
            "science_target_count": len(result.science_targets),
        }

    def _target_lookup(self, a: TargetLookupArgs, mission_id: UUID) -> dict[str, Any]:
        result = self._completed(a.analysis_id)
        targets = [t for t in result.science_targets if a.target_id is None or t.id == a.target_id]
        if a.target_id is not None and not targets:
            raise ToolFailure("not_found", f"target {a.target_id} is not part of analysis {a.analysis_id}")
        return {
            "analysis_id": str(result.id), "count": len(targets), "targets": [t.model_dump(mode="json") for t in targets],
            "note": None if targets else "This analysis produced no science targets: no science objective is supported yet, so absence of targets is not evidence of absence of minerals.",
        }

    def _dataset_status(self, a: DatasetStatusArgs, mission_id: UUID) -> dict[str, Any]:
        if a.analysis_id is not None:
            datasets = self._completed(a.analysis_id).datasets
        else:
            datasets = [mola.dataset_record()]
        return {"analysis_id": str(a.analysis_id) if a.analysis_id else None,
                "datasets": [d.model_dump(mode="json", exclude={"source_spatial_metadata"}) for d in datasets]}


class UnknownToolError(ValueError):
    """The requested tool name is not part of the contract; the call cannot be represented."""


class ToolFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _job_dict(job) -> dict[str, Any]:
    return {"analysis_id": str(job.id), "stage": job.stage.value, "progress_percent": job.progress_percent,
            "message": job.message, "error_code": job.error_code, "warnings": list(job.warnings)}
