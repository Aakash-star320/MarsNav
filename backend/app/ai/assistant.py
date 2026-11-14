"""Deterministic assistant: understands a small set of requests, runs validated tools, and answers
with values copied from their results. No language model is needed; a model can later replace
``plan`` and still go through the same validated ``ToolExecutor``.

Hard rules: coordinates come only from the user's own message (labelled west/south/east/north) or from
a mission area supplied by a provider, never invented; every number in an answer comes from a tool
result; routing and navigation questions are answered with the real limitation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from app.analyzer.orchestration.service import AnalysisService
from app.ai.tools.registry import ToolExecutor, UnknownToolError
from app.schemas import (
    AssistantAction,
    AssistantCitation,
    AssistantRequest,
    AssistantResponse,
    AssistantToolCall,
    AssistantToolName,
    BoundingBox,
    JobStage,
)

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NUM = r"(-?\d+(?:\.\d+)?)"
SCOPE = ("I can start a terrain analysis for an area, report its status, summarize the result (area, elevation, slope), "
         "list science targets and describe the data sources. I can't answer general questions about Mars here.")
WORDS = {
    "route": ("route", "path", "navigate", "navigation", "waypoint", "replan", "directions", "walk to"),
    "start": ("analyze", "analyse", "analysis of", "run an analysis", "start an analysis", "start analysis"),
    "targets": ("target", "mineral", "clay", "carbonate", "science site", "science stop", "hydrated"),
    "data": ("dataset", "data source", "source", "provenance", "which data", "resolution", "where does the data"),
    "status": ("status", "progress", "finished", "done yet", "ready yet", "is it done", "how long"),
    "result": ("result", "summary", "summarize", "summarise", "steep", "slope", "elevation", "relief", "how big", "terrain", "area"),
}


def _has(msg: str, key: str) -> bool:
    return any(w in msg for w in WORDS[key])


def parse_bounds(message: str) -> BoundingBox | None:
    """Bounds only if the user labelled all four edges; nothing is guessed from unlabelled numbers."""
    found: dict[str, float] = {}
    for edge in ("west", "south", "east", "north"):
        m = re.search(rf"\b{edge}\b\s*[:=]?\s*{NUM}", message, re.IGNORECASE)
        if m:
            found[edge] = float(m.group(1))
    if len(found) < 4:
        return None
    try:
        return BoundingBox(west_deg_east=found["west"], south_deg=found["south"], east_deg_east=found["east"], north_deg=found["north"])
    except ValueError:
        return None


@dataclass
class Plan:
    steps: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    reply: str | None = None            # used when no tool can run (a question back, or a scoped limitation)


class AssistantService:
    def __init__(self, analyses: AnalysisService, executor: ToolExecutor | None = None,
                 mission_bounds: Callable[[UUID], BoundingBox | None] = lambda mission_id: None) -> None:
        self._analyses = analyses
        self._exec = executor or ToolExecutor(analyses)
        self._mission_bounds = mission_bounds

    # -- planning ---------------------------------------------------------------------------------
    def plan(self, req: AssistantRequest) -> Plan:
        msg = req.message.lower()
        explicit = UUID_RE.search(req.message)
        latest = self._analyses.latest_for_mission(req.mission_id)
        latest_done = self._analyses.latest_for_mission(req.mission_id, completed_only=True)

        def target_id(done: bool) -> str | None:
            if explicit:
                return explicit.group(0)
            if req.analysis_id is not None:
                return str(req.analysis_id)
            job = latest_done if done else latest
            return str(job.id) if job else None

        if _has(msg, "route"):
            return Plan([("route_create", {})])
        if _has(msg, "start") and not _has(msg, "status"):
            bounds = parse_bounds(req.message) or req.selected_area or self._mission_bounds(req.mission_id)
            if bounds is None:
                return Plan(reply="Which area should I analyze? Select it on the map, or give the edges in degrees, for example: "
                                  "west 77.0 south 18.1 east 77.8 north 18.8. I won't guess an area.")
            return Plan([("analysis_start", {"bounds": bounds.model_dump()})])
        for key, tool, done in (("targets", "target_lookup", True), ("data", "dataset_status", False), ("status", "analysis_status", False), ("result", "analysis_result", True)):
            if _has(msg, key):
                aid = target_id(done)
                if aid is None:
                    if key == "data":
                        return Plan([("dataset_status", {})])
                    return Plan(reply="There is no analysis for this mission yet. Select an area and start one first." if latest is None else
                                f"The analysis for this mission is {latest.stage.value}; I can summarize it once it has completed.")
                return Plan([(tool, {"analysis_id": aid} if key != "data" else {"analysis_id": aid})])
        return Plan(reply=SCOPE)

    # -- execution --------------------------------------------------------------------------------
    def handle(self, req: AssistantRequest) -> AssistantResponse:
        plan = self.plan(req)
        if not plan.steps:
            return AssistantResponse(message=plan.reply or SCOPE)
        calls: list[AssistantToolCall] = []
        warnings: list[str] = []
        for name, args in plan.steps:
            try:
                calls.append(self._exec.execute(name, args, req.mission_id))
            except UnknownToolError as exc:
                warnings.append(str(exc))
        parts, actions, citations = [], [], []
        for call in calls:
            text, acts, cites, warns = self._describe(call)
            parts.append(text)
            actions += acts
            citations += cites
            warnings += warns
        return AssistantResponse(message=" ".join(parts) or SCOPE, tool_calls=calls, citations=citations, actions=actions,
                                 warnings=list(dict.fromkeys(warnings)))

    # -- wording: values are copied from tool results ----------------------------------------------
    @staticmethod
    def _describe(call: AssistantToolCall) -> tuple[str, list[AssistantAction], list[AssistantCitation], list[str]]:
        if call.status != "completed" or call.result is None:
            return f"I couldn't do that: {call.error_message}", [], [], []
        r, name = call.result, call.name
        if name == AssistantToolName.analysis_start:
            return (f"Started analysis {r['analysis_id']} ({r['stage']}). Ask me for its status, or its summary once it has completed.", [], [], [])
        if name == AssistantToolName.analysis_status:
            tail = f" Error: {r['error_code']}." if r.get("error_code") else ""
            return (f"Analysis {r['analysis_id']} is {r['stage']} ({r['progress_percent']}%): {r['message']}.{tail}", [], [], r.get("warnings", []))
        if name == AssistantToolName.analysis_result:
            s = r["statistics"]
            steep = "no slope is defined" if s["slope_exceedance_fraction"] is None else (
                f"{100 * s['slope_exceedance_fraction']:.1f}% of cells are steeper than {s['slope_limit_deg']:g}° "
                f"({s['slope_exceedance_cells']} of {s['slope_denominator_cells']} cells with a defined slope)")
            text = (f"Analysis {r['analysis_id']} covers {s['area_km2']:.0f} km² in cells of {s['cell_size_x_m']:.0f} × {s['cell_size_y_m']:.0f} m. "
                    f"Elevation runs from {s['elevation_min_m']:.0f} to {s['elevation_max_m']:.0f} m; mean slope is {s['slope_mean_deg']:.1f}° "
                    f"and the maximum is {s['slope_max_deg']:.1f}°; {steep}. {s['valid_percent']:.1f}% of cells have valid data. "
                    "This is a coarse global elevation model, so it supports broad planning only and is not a safety assessment.")
            acts = []
            if r.get("bounds"):
                acts.append(AssistantAction(type="focus_roi", payload={"bounds": r["bounds"], "analysis_id": r["analysis_id"]}))
            if "elevation" in r["layers"]:
                acts.append(AssistantAction(type="select_layer", payload={"layer_id": r["layers"]["elevation"], "kind": "elevation"}))
            return text, acts, _citations(r.get("sources", [])), list(r["warnings"])
        if name == AssistantToolName.target_lookup:
            if r["count"] == 0:
                return (r["note"], [], [], [])
            first = r["targets"][0]
            acts = [AssistantAction(type="focus_target", payload={"target_id": first["id"]})] if r["count"] == 1 else []
            names = ", ".join(f"{t['title']} (score {t['relevance_score']:g}, confidence {t['confidence']})" for t in r["targets"])
            return (f"{r['count']} science target(s): {names}.", acts, [], [])
        if name == AssistantToolName.dataset_status:
            ds = r["datasets"]
            lines = "; ".join(f"{d['product_id']} (version {d.get('version') or 'unknown'}, "
                              f"{d.get('resolution_m_per_px') or 'unknown'} m/px, freshness: {d['freshness']})" for d in ds)
            cites = [AssistantCitation(id=f"dataset-{d['id']}", source_uri=d["provenance_url"], title=d["product_id"]) for d in ds if d.get("provenance_url")]
            return (f"Data sources: {lines}. Freshness is reported as unverified because no update check has been run.", [], cites, [])
        return ("Done.", [], [], [])


def _citations(sources: list[dict[str, Any]]) -> list[AssistantCitation]:
    return [AssistantCitation(id=f"source-{s['product_id']}", source_uri=s["provenance_url"], title=s["product_id"])
            for s in sources if s.get("provenance_url")]
