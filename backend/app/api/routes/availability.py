"""Objective availability and the data budget (see ``analyzer/discovery/availability.py`` and ``analyzer/validation/data_budget.py``)."""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.analyzer.discovery.availability import AreaTooLarge, AvailabilityRequest, AvailabilityResult, FetchJson, check_availability
from app.analyzer.validation.data_budget import DataBudget, get_budget
from app.core.config import settings

router = APIRouter()


class DataBudgetSnapshot(BaseModel):
    per_analysis_cap_bytes: int
    session_cap_bytes: int
    session_used_bytes: int
    analyses_counted: int


@lru_cache
def get_checker() -> Callable[..., AvailabilityResult]:
    """The function the endpoint calls; tests replace it with one that has a fake catalog."""
    return check_availability


@router.post("/objectives/check", response_model=AvailabilityResult)
def check_objective(req: AvailabilityRequest, check: Callable[..., AvailabilityResult] = Depends(get_checker)) -> AvailabilityResult:
    """Is there NASA data for this objective in this area, and can this tool use it? Nothing is downloaded."""
    try:
        return check(req.objective, req.bounds, max_area_km2=settings.analyzer_max_area_km2)
    except AreaTooLarge as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/data-budget", response_model=DataBudgetSnapshot)
def read_data_budget(budget: DataBudget = Depends(get_budget)) -> DataBudgetSnapshot:
    return DataBudgetSnapshot(**budget.snapshot())
