import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.assistant import AssistantService, parse_bounds
from app.ai.tools.registry import ToolExecutor, UnknownToolError, tool_specs
from app.analyzer.orchestration.pipeline import AnalyzerDeps
from app.analyzer.orchestration.service import AnalysisService
from app.api.routes import assistant as assistant_routes
from app.connectors.usgs.mola import MolaLayout
from app.schemas import AnalysisJob, AssistantRequest, AssistantToolName, JobStage

SMALL = MolaLayout(url="https://example.test/dem.tif", width=720, height=360, data_offset=100, deg_per_px=0.5,
                   pixel_size_m=1000.0, file_size=0, etag="test")
_r, _c = np.indices((SMALL.height, SMALL.width))
BLOB = b"\0" * SMALL.data_offset + (10 * _r + 100 * _c).astype("<i2").tobytes()
MISSION = UUID("00000000-0000-0000-0000-0000000000ee")
NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)
AREA = "west 10 south 20 east 14 north 24"


def make(tmp_path):
    svc = AnalysisService(AnalyzerDeps(fetch_range=lambda a, b: BLOB[a:b + 1], out_dir=tmp_path, mola_layout=SMALL, max_area_km2=1e9),
                          clock=lambda: NOW)
    return svc, ToolExecutor(svc, new_id=lambda: "call-1"), AssistantService(svc, ToolExecutor(svc))


def ask(assistant, text, mission=MISSION):
    return assistant.handle(AssistantRequest(mission_id=mission, message=text))


# -- tools ---------------------------------------------------------------------------------------
def test_every_contract_tool_has_a_spec_and_a_schema() -> None:
    specs = {s.name: s for s in tool_specs()}
    assert set(specs) == set(AssistantToolName)
    assert "bounds" in specs[AssistantToolName.analysis_start].arguments_schema["properties"]
    assert not specs[AssistantToolName.route_create].available and specs[AssistantToolName.analysis_result].available


def test_invalid_arguments_are_rejected_before_running(tmp_path) -> None:
    svc, ex, _ = make(tmp_path)
    bad = ex.execute("analysis_start", {"bounds": {"west_deg_east": 14, "south_deg": 20, "east_deg_east": 10, "north_deg": 24}}, MISSION)
    assert bad.status == "rejected" and bad.error_code == "invalid_arguments" and "east_deg_east" in bad.error_message
    assert ex.execute("analysis_status", {"analysis_id": "not-a-uuid"}, MISSION).status == "rejected"
    assert ex.execute("analysis_result", {"analysis_id": str(uuid4()), "slope_limit_deg": 99}, MISSION).error_code == "invalid_arguments"
    assert svc.latest_for_mission(MISSION) is None                          # nothing was started


def test_unknown_tools_cannot_be_represented_and_unavailable_ones_say_why(tmp_path) -> None:
    _, ex, _ = make(tmp_path)
    with pytest.raises(UnknownToolError):
        ex.execute("delete_everything", {}, MISSION)
    call = ex.execute("route_create", {"anything": 1}, MISSION)
    assert call.status == "rejected" and call.error_code == "not_available" and "routing service" in call.error_message


def test_results_are_summaries_without_raster_data(tmp_path) -> None:
    svc, ex, _ = make(tmp_path)
    start = ex.execute("analysis_start", {"bounds": {"west_deg_east": 10, "south_deg": 20, "east_deg_east": 14, "north_deg": 24}}, MISSION)
    assert start.status == "completed" and start.result["stage"] in {"queued", "discovery", "completed"}
    svc.wait_idle()
    aid = start.result["analysis_id"]
    res = ex.execute("analysis_result", {"analysis_id": aid}, MISSION)
    assert res.status == "completed" and set(res.result["layers"]) == {"elevation", "slope", "roughness", "validity", "source"}
    assert len(json.dumps(res.result)) < 6000                               # no arrays, no pixel data
    assert res.result["statistics"]["cells_total"] == 64 and res.result["science_target_count"] == 0
    unknown = ex.execute("analysis_status", {"analysis_id": str(uuid4())}, MISSION)
    assert unknown.status == "failed" and unknown.error_code == "not_found"


def test_unfinished_analysis_is_not_ready(tmp_path) -> None:
    svc, ex, _ = make(tmp_path)
    job = AnalysisJob(id=uuid4(), mission_id=MISSION, stage=JobStage.terrain, progress_percent=80, message="x", created_at=NOW, updated_at=NOW)
    svc._jobs[job.id] = job
    call = ex.execute("analysis_result", {"analysis_id": str(job.id)}, MISSION)
    assert call.status == "failed" and call.error_code == "not_ready"


def test_target_lookup_is_honest_when_there_are_no_targets(tmp_path) -> None:
    svc, ex, _ = make(tmp_path)
    aid = ex.execute("analysis_start", {"bounds": {"west_deg_east": 10, "south_deg": 20, "east_deg_east": 14, "north_deg": 24}}, MISSION).result["analysis_id"]
    svc.wait_idle()
    out = ex.execute("target_lookup", {"analysis_id": aid}, MISSION)
    assert out.result["count"] == 0 and "not evidence of absence" in out.result["note"]
    assert ex.execute("target_lookup", {"analysis_id": aid, "target_id": str(uuid4())}, MISSION).error_code == "not_found"


def test_dataset_status_without_an_analysis_lists_the_catalog(tmp_path) -> None:
    _, ex, _ = make(tmp_path)
    out = ex.execute("dataset_status", {}, MISSION)
    assert out.status == "completed" and out.result["datasets"][0]["product_id"].startswith("Mars_MGS_MOLA")


# -- assistant -----------------------------------------------------------------------------------
def test_bounds_come_only_from_labelled_values() -> None:
    b = parse_bounds("analyze " + AREA)
    assert (b.west_deg_east, b.south_deg, b.east_deg_east, b.north_deg) == (10, 20, 14, 24)
    assert parse_bounds("analyze around 77, 18") is None
    assert parse_bounds("west 10 south 20 east 5 north 24") is None


def test_it_asks_for_the_area_instead_of_guessing(tmp_path) -> None:
    svc, _, bot = make(tmp_path)
    for text in ("Analyze this region", "analyze near Jezero", "analyze around 18.4, 77.4"):
        r = ask(bot, text)
        assert r.tool_calls == [] and "won't guess" in r.message
    assert svc.latest_for_mission(MISSION) is None


def test_full_conversation_uses_real_results(tmp_path) -> None:
    svc, ex, bot = make(tmp_path)
    started = ask(bot, "Please analyze " + AREA)
    assert started.tool_calls[0].name == AssistantToolName.analysis_start and started.tool_calls[0].status == "completed"
    aid = started.tool_calls[0].result["analysis_id"]
    assert aid in started.message
    svc.wait_idle()
    status = ask(bot, "is it done? what is the status")
    assert "completed" in status.message and status.tool_calls[0].name == AssistantToolName.analysis_status
    summary = ask(bot, "Summarize the terrain")
    tool = summary.tool_calls[0]
    s = tool.result["statistics"]
    assert tool.name == AssistantToolName.analysis_result
    assert f"{s['area_km2']:.0f} km²" in summary.message and f"{s['slope_max_deg']:.1f}°" in summary.message
    assert "not a safety assessment" in summary.message
    kinds = {a.type for a in summary.actions}
    assert kinds == {"focus_roi", "select_layer"}
    layer_action = next(a for a in summary.actions if a.type == "select_layer")
    assert layer_action.payload["layer_id"] == tool.result["layers"]["elevation"]
    assert summary.citations and summary.citations[0].source_uri.startswith("https://")
    assert any("463 m" in w for w in summary.warnings)


def test_targets_data_and_routes(tmp_path) -> None:
    svc, _, bot = make(tmp_path)
    ask(bot, "analyze " + AREA)
    svc.wait_idle()
    targets = ask(bot, "Are there any hydrated minerals?")
    assert targets.tool_calls[0].result["count"] == 0 and "not evidence of absence" in targets.message
    data = ask(bot, "Which data sources did you use?")
    assert data.tool_calls[0].name == AssistantToolName.dataset_status and "Mars_MGS_MOLA_DEM_mosaic_global_463m" in data.message
    assert data.citations and "unverified" in data.message
    route = ask(bot, "Plan a route to the crater")
    assert route.tool_calls[0].status == "rejected" and "not connected" in route.message


def test_out_of_scope_and_empty_missions(tmp_path) -> None:
    _, _, bot = make(tmp_path)
    r = ask(bot, "What's the weather on Mars tomorrow?")
    assert r.tool_calls == [] and "can't answer general questions" in r.message
    empty = ask(bot, "give me a summary", mission=uuid4())
    assert empty.tool_calls == [] and "no analysis" in empty.message


def test_a_mission_never_sees_another_missions_analysis(tmp_path) -> None:
    svc, _, bot = make(tmp_path)
    ask(bot, "analyze " + AREA)
    svc.wait_idle()
    other = ask(bot, "summarize the terrain", mission=uuid4())
    assert other.tool_calls == [] and "no analysis" in other.message


def test_http_endpoint(tmp_path) -> None:
    svc, _, bot = make(tmp_path)
    app = FastAPI()
    app.include_router(assistant_routes.router, prefix="/api/v1")
    app.dependency_overrides[assistant_routes.get_assistant] = lambda: bot
    c = TestClient(app)
    r = c.post("/api/v1/assistant/messages", json={"mission_id": str(MISSION), "message": "analyze " + AREA})
    assert r.status_code == 200 and r.json()["tool_calls"][0]["name"] == "analysis_start"
    assert c.post("/api/v1/assistant/messages", json={"mission_id": str(MISSION), "message": ""}).status_code == 422
