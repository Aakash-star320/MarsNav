"""Language-model assistant: the model decides what to look up, the validated tool registry does it.

Protocol (plain JSON text, so it works with any hosted model): each model turn is one JSON object, either
``{"action": "tool", "tool": "<name>", "arguments": {...}}`` or ``{"action": "final", "message": "<answer>"}``.

Safety rules enforced here, not left to the prompt:
* only tools in an explicit allowlist can run, with arguments validated by the registry's Pydantic models;
* an ``analysis_id`` must be one the user's request or an earlier tool result supplied, never one the model made up;
* tools that start work or belong to other services (analysis start, routing, navigation) are not offered;
* the step count is bounded, malformed output gets one repair attempt, then the caller falls back to rule-based;
* map actions, citations and warnings come from the tool results, not from the model's text.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.ai.assistant import AssistantService, UUID_RE
from app.ai.llm.gemma import GemmaClient, LlmUnavailable
from app.ai.tools.registry import ToolExecutor, UnknownToolError, tool_specs
from app.analyzer.orchestration.service import AnalysisService
from app.schemas import AssistantRequest, AssistantResponse, AssistantToolCall, AssistantToolName

MAX_TOOL_CALLS = 4
MAX_REPAIRS = 1
RESULT_CHARS = 6000
ANSWER_CHARS = 3500
OFFERED = (AssistantToolName.analysis_status, AssistantToolName.analysis_result,
           AssistantToolName.target_lookup, AssistantToolName.dataset_status)

SYSTEM = """You are the MarsNav assistant, inside a Mars surface-planning tool. You help a user understand a terrain analysis of an area of Mars.

You can only look things up with the tools below. Rules:
- Every number, name and fact about the analysis must come from a tool result. Copy numbers exactly. Never invent coordinates, elevations, slopes, targets or analysis ids.
- Only use an analysis_id that appears in CONTEXT or in an earlier tool result.
- Spectral candidates are heuristic screens of summary parameters, not identified minerals. Missing coverage is never evidence of absence. The elevation data is coarse (463 m cells): broad planning only, not a safety assessment, no rock-scale hazards.
- You cannot start analyses, plan routes or navigate. If asked, say the user can use the buttons or say "analyze this region", and routing is not connected to the assistant yet.
- If there is no analysis yet, say so and tell the user to select an area and analyze it.
- General questions about Mars science may be answered briefly in plain terms, but say they are general background, not from this analysis. Decline anything unrelated to Mars planning in one sentence.
- Keep answers short (2 to 6 sentences). No markdown headings.

Reply with EXACTLY ONE JSON object and nothing else, in one of two forms:
{"action": "tool", "tool": "<tool name>", "arguments": { ... }}
{"action": "final", "message": "<your answer to the user>"}
"""


def _tool_block() -> str:
    lines = []
    for spec in tool_specs():
        if spec.name in OFFERED:
            props = spec.arguments_schema.get("properties", {})
            lines.append(f'- {spec.name.value}: {spec.description} Arguments: {json.dumps({k: v.get("type", v.get("format", "string")) for k, v in props.items()})}')
    return "TOOLS:\n" + "\n".join(lines)


def _context_block(req: AssistantRequest, analyses: AnalysisService) -> str:
    out = ["CONTEXT:"]
    if req.analysis_id is not None:
        job = analyses.get_job(req.analysis_id)
        out.append(f"- Current analysis id: {req.analysis_id}" + (f" (stage: {job.stage.value})" if job else " (not found)"))
    else:
        out.append("- There is no current analysis yet.")
    if req.selected_area is not None:
        a = req.selected_area
        out.append(f"- Selected area: west {a.west_deg_east:.4f}, south {a.south_deg:.4f}, east {a.east_deg_east:.4f}, north {a.north_deg:.4f} degrees (planetocentric, east-positive).")
    else:
        out.append("- No area is selected.")
    return "\n".join(out)


_PLACEHOLDER = re.compile(r"^\W*(\.{2,}|…|<[^>]*>|your answer.*|answer here)\W*$", re.IGNORECASE)


def _real_answer(message: object) -> bool:
    """A usable final answer: not blank, not a bare placeholder such as '...' or '<your answer>', and at least a few characters of words."""
    if not isinstance(message, str):
        return False
    text = message.strip()
    return len(re.findall(r"\w", text)) >= 3 and not _PLACEHOLDER.match(text)


def parse_reply(text: str) -> dict[str, Any] | None:
    """The first JSON object in the reply (tolerates code fences and surrounding words), or None."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start = cleaned.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            esc = (ch == "\\") and not esc
            if ch == '"' and not esc:
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(cleaned[start:i + 1])
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def _rounded(value: Any) -> Any:
    """Floats to 3 decimals: the model repeats what it sees, and 0.9302750825881958 helps nobody."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return value


def _compact(call: AssistantToolCall) -> str:
    payload = {"tool": call.name.value, "status": call.status, "result": _rounded(call.result), "error": call.error_message}
    text = json.dumps(payload, default=str, separators=(",", ":"))
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + '..."truncated"}'


def _ids_in(value: Any, into: set[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "analysis_id" and isinstance(v, str):
                into.add(v.lower())
            _ids_in(v, into)
    elif isinstance(value, list):
        for v in value:
            _ids_in(v, into)


class LlmAssistant:
    def __init__(self, client: GemmaClient, analyses: AnalysisService, executor: ToolExecutor | None = None) -> None:
        self._client, self._analyses = client, analyses
        self._exec = executor or ToolExecutor(analyses)

    def handle(self, req: AssistantRequest) -> AssistantResponse:
        known: set[str] = {m.group(0).lower() for m in UUID_RE.finditer(req.message)}
        if req.analysis_id is not None:
            known.add(str(req.analysis_id).lower())
        turns: list[tuple[str, str]] = [("user", f"{SYSTEM}\n{_tool_block()}\n\n{_context_block(req, self._analyses)}\n\nUSER MESSAGE:\n{req.message}")]
        calls: list[AssistantToolCall] = []
        repairs = 0
        out_of_steps = False
        final: str | None = None
        while final is None:
            raw = self._client.generate(turns)
            obj = parse_reply(raw)
            action = obj.get("action") if obj else None
            if action == "final" and _real_answer(obj.get("message")):
                final = obj["message"].strip()[:ANSWER_CHARS]
                break
            if action == "tool" and isinstance(obj.get("tool"), str):
                if len(calls) >= MAX_TOOL_CALLS:
                    if out_of_steps:
                        raise LlmUnavailable("too_many_steps", "the language model kept asking for tools instead of answering")
                    out_of_steps = True
                    turns += [("model", json.dumps(obj, separators=(",", ":"))), ("user", 'No more tool calls are allowed. Reply now with {"action":"final","message":"..."} using only the results you have.')]
                    continue
                call = self._run_tool(obj["tool"], obj.get("arguments"), req, known)
                calls.append(call)
                if call.result:
                    _ids_in(call.result, known)
                turns += [("model", json.dumps(obj, separators=(",", ":"))), ("user", f"TOOL RESULT:\n{_compact(call)}\n\nNow reply with one JSON object (another tool call, or the final answer).")]
                continue
            repairs += 1
            if repairs > MAX_REPAIRS:
                raise LlmUnavailable("bad_format", "the language model did not follow the reply format")
            turns += [("model", raw[:2000]), ("user", 'Your reply was not a valid answer. Reply again with EXACTLY ONE JSON object: either a tool call with the keys "action" (value "tool"), "tool" and "arguments", or a final answer with the keys "action" (value "final") and "message" holding your real answer in full sentences.')]
        return self._respond(final, calls)

    # -- tools ------------------------------------------------------------------------------------
    def _run_tool(self, name: str, arguments: Any, req: AssistantRequest, known: set[str]) -> AssistantToolCall:
        args = dict(arguments) if isinstance(arguments, dict) else {}
        try:
            tool = AssistantToolName(name)
        except ValueError:
            return self._rejected(AssistantToolName.dataset_status, args, "unknown_tool", f"'{name}' is not a tool")
        if tool not in OFFERED:
            return self._rejected(tool, args, "not_offered", f"'{name}' is not available to the assistant")
        given = args.get("analysis_id")
        if given is not None and str(given).lower() not in known:
            return self._rejected(tool, args, "unknown_analysis", "that analysis_id was not provided by the user or a tool; use the id from CONTEXT")
        if given is None and tool != AssistantToolName.dataset_status and req.analysis_id is not None:
            args["analysis_id"] = str(req.analysis_id)          # the only analysis in play; saves the model guessing
        try:
            return self._exec.execute(name, args, req.mission_id)
        except UnknownToolError as exc:
            return self._rejected(tool, args, "unknown_tool", str(exc))

    @staticmethod
    def _rejected(tool: AssistantToolName, args: dict[str, Any], code: str, message: str) -> AssistantToolCall:
        return AssistantToolCall(id=f"rejected-{code}", name=tool, arguments={k: v for k, v in args.items() if isinstance(v, (str, int, float, bool))},
                                 status="rejected", error_code=code, error_message=message)

    # -- response: actions, citations and warnings come from tool results ----------------------------
    @staticmethod
    def _respond(message: str, calls: list[AssistantToolCall]) -> AssistantResponse:
        actions, citations, warnings = [], [], []
        for call in calls:
            if call.status != "completed":
                continue
            _, acts, cites, warns = AssistantService._describe(call)
            actions += acts
            citations += cites
            warnings += warns
        return AssistantResponse(message=message, tool_calls=calls, citations=citations, actions=actions, warnings=list(dict.fromkeys(warnings)))
