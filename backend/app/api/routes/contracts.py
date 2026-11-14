"""Schema-bearing endpoint skeletons. Domain owners replace the 501 responses with real implementations."""
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query, status
from app.schemas import (
    AssistantRequest, AssistantResponse, CreateAnalysisRequest,
    CreateMissionRequest, DatasetCategory, DatasetRecord, DatasetRefreshJob,
    FreshnessState, Mission, NavigationGuideRequest, NavigationInstruction,
    OfflinePackageRequest, OfflinePackageStatus,
    ReplanRequest, RouteRequest, RouteResult,
)

router = APIRouter()

def pending() -> None:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Contract scaffold")

@router.post("/missions", response_model=Mission, status_code=status.HTTP_201_CREATED)
def create_mission(_: CreateMissionRequest) -> Mission: pending()
@router.get("/missions/{mission_id}", response_model=Mission)
def get_mission(mission_id: UUID) -> Mission: pending()
@router.get("/datasets", response_model=list[DatasetRecord])
def list_datasets(
    categories: list[DatasetCategory] = Query(default=[]),
    freshness: list[FreshnessState] = Query(default=[]),
) -> list[DatasetRecord]:
    """Dataset owner may add typed AOI query fields without accepting free-form geometry."""
    pending()
@router.get("/datasets/{dataset_id}", response_model=DatasetRecord)
def get_dataset(dataset_id: UUID) -> DatasetRecord: pending()
@router.post("/datasets/{dataset_id}/refresh", response_model=DatasetRefreshJob, status_code=status.HTTP_202_ACCEPTED)
def refresh_dataset(dataset_id: UUID) -> DatasetRefreshJob: pending()
@router.get("/missions/{mission_id}/offline-package", response_model=OfflinePackageStatus)
def get_offline_package(mission_id: UUID) -> OfflinePackageStatus: pending()
@router.post("/missions/{mission_id}/offline-package", response_model=OfflinePackageStatus, status_code=status.HTTP_202_ACCEPTED)
def prepare_offline_package(mission_id: UUID, _: OfflinePackageRequest) -> OfflinePackageStatus: pending()
@router.post("/routes", response_model=RouteResult)
def create_route(_: RouteRequest) -> RouteResult: pending()
@router.post("/routes/{route_id}/replan", response_model=RouteResult)
def replan_route(route_id: UUID, _: ReplanRequest) -> RouteResult: pending()
@router.post("/navigation/guide", response_model=NavigationInstruction)
def navigation_guide(_: NavigationGuideRequest) -> NavigationInstruction: pending()
@router.post("/assistant/messages", response_model=AssistantResponse)
def assistant_message(_: AssistantRequest) -> AssistantResponse: pending()
