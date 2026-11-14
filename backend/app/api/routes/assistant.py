"""Assistant endpoints (analyzer-owned).

``POST /assistant/messages`` answers with a Gemma model when ``GEMMA_MODEL`` and ``GEMMA_API_KEY`` are set, and
with the rule-based assistant otherwise (or when the model is unavailable, with a warning saying so). Either way
tool arguments are validated and answers are built from tool results. ``GET /assistant/status`` says which mode is active.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai.assistant import AssistantService
from app.ai.llm.gemma import GemmaClient, LlmUnavailable
from app.ai.llm_assistant import LlmAssistant
from app.api.routes.analyses import get_service
from app.core.config import settings
from app.schemas import AssistantRequest, AssistantResponse

router = APIRouter()


class AssistantStatus(BaseModel):
    mode: str                 # "gemma" or "rule_based"
    model: str | None = None  # the configured model name (never the key)


@lru_cache
def get_assistant() -> AssistantService:
    return AssistantService(get_service())


@lru_cache
def get_llm() -> LlmAssistant | None:
    client = GemmaClient(settings.gemma_api_key, settings.gemma_model, settings.gemma_api_base)
    return LlmAssistant(client, get_service()) if client.configured else None


@router.get("/assistant/status", response_model=AssistantStatus)
def assistant_status(llm: LlmAssistant | None = Depends(get_llm)) -> AssistantStatus:
    return AssistantStatus(mode="gemma", model=settings.gemma_model) if llm is not None else AssistantStatus(mode="rule_based")


@router.post("/assistant/messages", response_model=AssistantResponse)
def assistant_message(req: AssistantRequest, assistant: AssistantService = Depends(get_assistant),
                      llm: LlmAssistant | None = Depends(get_llm)) -> AssistantResponse:
    if llm is not None:
        try:
            return llm.handle(req)
        except LlmUnavailable as exc:
            fallback = assistant.handle(req)
            fallback.warnings = [f"The language model was unavailable ({exc.code}); this answer is from the rule-based assistant.", *fallback.warnings]
            return fallback
    return assistant.handle(req)
