from fastapi import APIRouter
from .routes import analyses, assistant, health, contracts, mission_plans, objectives, routing

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["system"])
api_router.include_router(analyses.router, tags=["analyses"])
api_router.include_router(assistant.router, tags=["assistant"])
api_router.include_router(contracts.router, tags=["contracts"])
api_router.include_router(routing.router, tags=["routing"])
api_router.include_router(mission_plans.router, tags=["mission-plans"])
api_router.include_router(objectives.router, tags=["objectives"])
