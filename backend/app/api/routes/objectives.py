"""The science objectives this tool can really answer (``GET /objectives``)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.analyzer.science.objectives import list_objectives

router = APIRouter()


class ObjectiveInfo(BaseModel):
    id: str
    label: str
    description: str
    keywords: list[str]
    data_used: list[str]
    limitation: str
    kind: str            # "spectral" (needs the CRISM data service) or "terrain" (uses the elevation data only)


@router.get("/objectives", response_model=list[ObjectiveInfo])
def objectives() -> list[ObjectiveInfo]:
    return [ObjectiveInfo(id=o.id, label=o.label, description=o.description, keywords=list(o.keywords), data_used=list(o.data_used),
                          limitation=o.limitation, kind=o.kind) for o in list_objectives()]
