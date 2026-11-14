"""Assistant endpoint (analyzer-owned): validated tool calls with answers copied from their results."""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends

from app.ai.assistant import AssistantService
from app.api.routes.analyses import get_service
from app.schemas import AssistantRequest, AssistantResponse

router = APIRouter()


@lru_cache
def get_assistant() -> AssistantService:
    return AssistantService(get_service())


@router.post("/assistant/messages", response_model=AssistantResponse)
def assistant_message(req: AssistantRequest, assistant: AssistantService = Depends(get_assistant)) -> AssistantResponse:
    return assistant.handle(req)
