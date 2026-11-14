import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.assistant import AssistantService
from app.ai.llm.gemma import GemmaClient, LlmUnavailable
from app.ai.llm_assistant import MAX_TOOL_CALLS, LlmAssistant, parse_reply
from app.api.routes import assistant as assistant_routes
from app.schemas import AssistantRequest, BoundingBox

from .test_assistant import AREA, MISSION, ask, make


class FakeModel:
    """Plays a scripted conversation; records what it was sent."""

    def __init__(self, *replies) -> None:
        self.replies, self.sent = list(replies), []
        self.configured, self.model = True, "fake-gemma"

    def generate(self, turns, **_):
        self.sent.append(list(turns))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)


def finished_analysis(tmp_path):
    svc, _, rule = make(tmp_path)
    ask(rule, f"analyze {AREA}")
    svc.wait_idle()
    return svc, svc.latest_for_mission(MISSION).id


def request(text, analysis_id=None, area=None):
    return AssistantRequest(mission_id=MISSION, message=text, analysis_id=analysis_id, selected_area=area)


# -- reply parsing ---------------------------------------------------------------------------------
def test_parse_reply_accepts_plain_fenced_and_chatty_json_and_rejects_the_rest() -> None:
    assert parse_reply('{"action":"final","message":"hi"}') == {"action": "final", "message": "hi"}
    assert parse_reply('```json\n{"action":"final","message":"a {b} c"}\n```')["message"] == "a {b} c"
    assert parse_reply('Sure! {"action":"tool","tool":"dataset_status","arguments":{}} done')["tool"] == "dataset_status"
    assert parse_reply("no json here") is None and parse_reply('{"broken": ') is None and parse_reply("[1,2]") is None


# -- the tool loop ---------------------------------------------------------------------------------
def test_model_looks_up_real_results_and_the_answer_carries_tool_calls_actions_and_warnings(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    model = FakeModel({"action": "tool", "tool": "analysis_result", "arguments": {"analysis_id": str(aid)}},
                      {"action": "final", "message": "The area is smooth."})
    resp = LlmAssistant(model, svc).handle(request("how steep is it?", analysis_id=aid))
    assert resp.message == "The area is smooth."
    assert [c.name.value for c in resp.tool_calls] == ["analysis_result"] and resp.tool_calls[0].status == "completed"
    assert {a.type for a in resp.actions} == {"focus_roi", "select_layer"} and resp.warnings          # derived from the tool result
    first_prompt = model.sent[0][0][1]
    assert str(aid) in first_prompt and "analysis_start" not in first_prompt and "route_create" not in first_prompt
    assert "TOOL RESULT" in model.sent[1][-1][1] and '"statistics"' in model.sent[1][-1][1]            # the model saw the real result


def test_numbers_are_rounded_before_the_model_sees_them(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    model = FakeModel({"action": "tool", "tool": "analysis_result", "arguments": {"analysis_id": str(aid)}}, {"action": "final", "message": "ok"})
    LlmAssistant(model, svc).handle(request("how steep?", analysis_id=aid))
    seen = model.sent[1][-1][1]
    import re
    assert not re.search(r"\d\.\d{4,}", seen)


def test_the_current_analysis_id_is_filled_in_when_the_model_omits_it(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    model = FakeModel({"action": "tool", "tool": "analysis_status", "arguments": {}}, {"action": "final", "message": "done"})
    resp = LlmAssistant(model, svc).handle(request("status?", analysis_id=aid))
    assert resp.tool_calls[0].status == "completed" and resp.tool_calls[0].result["analysis_id"] == str(aid)


def test_an_invented_analysis_id_never_reaches_the_service(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    made_up = str(uuid4())
    model = FakeModel({"action": "tool", "tool": "analysis_result", "arguments": {"analysis_id": made_up}}, {"action": "final", "message": "I could not find it."})
    resp = LlmAssistant(model, svc).handle(request("tell me about it", analysis_id=aid))
    assert resp.tool_calls[0].status == "rejected" and resp.tool_calls[0].error_code == "unknown_analysis"
    assert "not provided" in model.sent[1][-1][1]


def test_tools_that_start_work_or_belong_to_other_services_are_not_runnable(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    jobs_before = len(list(tmp_path.iterdir()))
    model = FakeModel({"action": "tool", "tool": "analysis_start", "arguments": {"bounds": {"west_deg_east": 1, "south_deg": 1, "east_deg_east": 2, "north_deg": 2}}},
                      {"action": "tool", "tool": "route_create", "arguments": {}},
                      {"action": "tool", "tool": "delete_everything", "arguments": {}},
                      {"action": "final", "message": "That is not available here."})
    resp = LlmAssistant(model, svc).handle(request("go and analyze somewhere else, then route me", analysis_id=aid))
    assert [c.status for c in resp.tool_calls] == ["rejected", "rejected", "rejected"]
    assert len(list(tmp_path.iterdir())) == jobs_before                           # no analysis was started


def test_malformed_output_gets_one_repair_then_fails_over(tmp_path) -> None:
    svc, _ = finished_analysis(tmp_path)
    ok = LlmAssistant(FakeModel("not json at all", {"action": "final", "message": "fixed"}), svc).handle(request("hi"))
    assert ok.message == "fixed"
    with pytest.raises(LlmUnavailable) as exc:
        LlmAssistant(FakeModel("nope", "still nope"), svc).handle(request("hi"))
    assert exc.value.code == "bad_format"


def test_the_tool_loop_is_bounded(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    forever = [{"action": "tool", "tool": "analysis_status", "arguments": {"analysis_id": str(aid)}}] * 20
    model = FakeModel(*forever, {"action": "final", "message": "unreachable"})
    with pytest.raises(LlmUnavailable):
        LlmAssistant(model, svc).handle(request("loop", analysis_id=aid))
    assert len(model.sent) <= MAX_TOOL_CALLS + 3


def test_client_errors_propagate_as_llm_unavailable(tmp_path) -> None:
    svc, _ = finished_analysis(tmp_path)
    with pytest.raises(LlmUnavailable) as exc:
        LlmAssistant(FakeModel(LlmUnavailable("timeout", "slow")), svc).handle(request("hi"))
    assert exc.value.code == "timeout"


# -- the Gemma client ---------------------------------------------------------------------------------
def client_with(handler, **kw):
    return GemmaClient("secret-key", "gemma-test", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)


def test_client_sends_the_key_only_in_a_header_and_returns_the_text() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(url=str(req.url), key=req.headers.get("x-goog-api-key"), body=json.loads(req.content))
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hel"}, {"text": "lo"}]}}]})
    assert client_with(handler).generate([("user", "hi")]) == "hello"
    assert seen["key"] == "secret-key" and "secret-key" not in seen["url"] and seen["url"].endswith("/models/gemma-test:generateContent")
    assert seen["body"]["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}]


@pytest.mark.parametrize("status,code", [(401, "api_key_rejected"), (403, "api_key_rejected"), (404, "model_not_found"), (400, "bad_request"), (429, "rate_limited"), (503, "server_error")])
def test_client_maps_http_failures_to_stable_codes_without_leaking_the_key(status, code) -> None:
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status, text="secret-key leaked in body?")
    with pytest.raises(LlmUnavailable) as exc:
        client_with(handler).generate([("user", "x")])
    assert exc.value.code == code and "secret-key" not in str(exc.value)
    assert len(calls) == (2 if status in (429, 503) else 1)                     # only transient errors are retried once


def test_client_handles_timeouts_empty_replies_and_missing_configuration() -> None:
    def slow(req):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(LlmUnavailable) as exc:
        client_with(slow).generate([("user", "x")])
    assert exc.value.code == "timeout"
    with pytest.raises(LlmUnavailable) as exc:
        client_with(lambda r: httpx.Response(200, json={"candidates": []})).generate([("user", "x")])
    assert exc.value.code == "empty_reply"
    blank = GemmaClient("", "")
    assert not blank.configured
    with pytest.raises(LlmUnavailable) as exc:
        blank.generate([("user", "x")])
    assert exc.value.code == "not_configured"


# -- the endpoints --------------------------------------------------------------------------------
def app_with(svc, llm):
    app = FastAPI()
    app.include_router(assistant_routes.router, prefix="/api/v1")
    app.dependency_overrides[assistant_routes.get_assistant] = lambda: AssistantService(svc)
    app.dependency_overrides[assistant_routes.get_llm] = lambda: llm
    return TestClient(app)


def test_status_reports_the_active_mode(tmp_path) -> None:
    svc, _ = finished_analysis(tmp_path)
    assert app_with(svc, None).get("/api/v1/assistant/status").json() == {"mode": "rule_based", "model": None}
    assert app_with(svc, LlmAssistant(FakeModel(), svc)).get("/api/v1/assistant/status").json()["mode"] == "gemma"


def test_endpoint_uses_the_model_and_falls_back_with_a_warning_when_it_is_down(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    body = {"mission_id": str(MISSION), "message": "what are the data sources?", "analysis_id": str(aid)}
    ok = app_with(svc, LlmAssistant(FakeModel({"action": "final", "message": "From the model."}), svc)).post("/api/v1/assistant/messages", json=body).json()
    assert ok["message"] == "From the model."
    down = app_with(svc, LlmAssistant(FakeModel(LlmUnavailable("rate_limited", "x")), svc)).post("/api/v1/assistant/messages", json=body).json()
    assert "rate_limited" in down["warnings"][0] and "rule-based" in down["warnings"][0] and "Data sources" in down["message"]
    plain = app_with(svc, None).post("/api/v1/assistant/messages", json=body).json()
    assert "Data sources" in plain["message"] and not any("language model" in w for w in plain["warnings"])


def test_rule_based_assistant_uses_the_ui_analysis_and_selected_area(tmp_path) -> None:
    svc, aid = finished_analysis(tmp_path)
    rule = AssistantService(svc)
    res = rule.handle(AssistantRequest(mission_id=uuid4(), message="summarize the result", analysis_id=aid))      # a different mission id, as the dashboard uses
    assert "covers" in res.message and res.tool_calls[0].status == "completed"
    area = BoundingBox(west_deg_east=10, south_deg=20, east_deg_east=12, north_deg=22)
    started = rule.handle(AssistantRequest(mission_id=uuid4(), message="analyze this area", selected_area=area))
    assert started.tool_calls and started.tool_calls[0].name.value == "analysis_start"
