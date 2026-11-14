from fastapi import APIRouter
from .routes import health, contracts

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["system"])
api_router.include_router(contracts.router, tags=["contracts"])
