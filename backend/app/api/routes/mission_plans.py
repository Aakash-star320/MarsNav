"""Mission-plan endpoints: choose science targets that fit the budget and plan the tour (see ``app.routing.mission_planner``)."""
from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.analyzer.integration.routing_terrain import TerrainAccessError
from app.api.routes.analyses import get_service
from app.routing.api_service import RouteNotFound
from app.routing.mission_api import MissionPlanApi
from app.routing.terrain import GridContractError
from app.schemas.mission_plan import MissionPlanRequest, MissionPlanResult

router = APIRouter()

_TERRAIN_STATUS = {"not_found": status.HTTP_404_NOT_FOUND, "not_ready": status.HTTP_409_CONFLICT,
                   "version_mismatch": status.HTTP_409_CONFLICT, "unavailable": status.HTTP_409_CONFLICT}


@lru_cache
def get_mission_planner() -> MissionPlanApi:
    return MissionPlanApi(get_service())


def _guard(call):
    try:
        return call()
    except TerrainAccessError as exc:
        raise HTTPException(_TERRAIN_STATUS.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY), detail=str(exc)) from exc
    except RouteNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (GridContractError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/mission-plans", response_model=MissionPlanResult)
def create_mission_plan(req: MissionPlanRequest, api: MissionPlanApi = Depends(get_mission_planner)) -> MissionPlanResult:
    return _guard(lambda: api.plan(req))


@router.get("/mission-plans/{plan_id}", response_model=MissionPlanResult)
def read_mission_plan(plan_id: UUID, api: MissionPlanApi = Depends(get_mission_planner)) -> MissionPlanResult:
    return _guard(lambda: api.get(plan_id))
