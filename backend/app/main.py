from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import api_router
from app.core.config import settings

app = FastAPI(title="MarsNav API", version="0.1.0", description="Contract scaffold; implementations follow the published API contract.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.include_router(api_router)
