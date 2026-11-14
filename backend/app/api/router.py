from fastapi import APIRouter
from .routes import analyses, assistant, health, contracts

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["system"])
api_router.include_router(analyses.router, tags=["analyses"])
api_router.include_router(assistant.router, tags=["assistant"])
api_router.include_router(contracts.router, tags=["contracts"])
