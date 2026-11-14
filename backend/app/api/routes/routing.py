"""Routing endpoints: plan, replan and navigation guidance (see ``app.routing.api_service``)."""
from __future__ import annotations

from functools import lru_cache
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.analyzer.integration.routing_terrain import TerrainAccessError
from app.api.routes.analyses import get_service
from app.routing.api_service import RouteConflict, RouteNotFound, RoutingApi
from app.routing.terrain import GridContractError
from app.schemas import NavigationGuideRequest, NavigationInstruction, ReplanRequest, RouteRequest, RouteResult

router = APIRouter()

_TERRAIN_STATUS = {"not_found": status.HTTP_404_NOT_FOUND, "not_ready": status.HTTP_409_CONFLICT,
                   "version_mismatch": status.HTTP_409_CONFLICT, "unavailable": status.HTTP_409_CONFLICT}


@lru_cache
def get_routing() -> RoutingApi:
    return RoutingApi(get_service())


def _guard(call):
    try:
        return call()
    except TerrainAccessError as exc:
        raise HTTPException(_TERRAIN_STATUS.get(exc.code, status.HTTP_422_UNPROCESSABLE_ENTITY), detail=str(exc)) from exc
    except RouteNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RouteConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (GridContractError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/routes", response_model=RouteResult)
def create_route(req: RouteRequest, api: RoutingApi = Depends(get_routing)) -> RouteResult:
    return _guard(lambda: api.plan(req))


@router.get("/routes/{route_id}", response_model=RouteResult)
def read_route(route_id: UUID, api: RoutingApi = Depends(get_routing)) -> RouteResult:
    return _guard(lambda: api.get(route_id))


@router.post("/routes/{route_id}/replan", response_model=RouteResult)
def replan_route(route_id: UUID, req: ReplanRequest, api: RoutingApi = Depends(get_routing)) -> RouteResult:
    if req.original_route_id != route_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="original_route_id does not match the path")
    return _guard(lambda: api.replan(req))


@router.post("/navigation/guide", response_model=NavigationInstruction)
def guide(req: NavigationGuideRequest, api: RoutingApi = Depends(get_routing)) -> NavigationInstruction:
    return _guard(lambda: api.guide(req))
