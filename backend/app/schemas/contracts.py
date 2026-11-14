"""Canonical Pydantic transport and inter-module contracts for MarsNav.

These models are the source of truth for REST payloads and typed boundaries
between analyzer, cache, routing, and AI modules.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator


class LonLat(BaseModel):
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg_east: float = Field(ge=-180, lt=180)


class BoundingBox(BaseModel):
    west_deg_east: float = Field(ge=-180, lt=180)
    south_deg: float = Field(ge=-90, le=90)
    east_deg_east: float = Field(ge=-180, lt=180)
    north_deg: float = Field(ge=-90, le=90)

    @field_validator("east_deg_east")
    @classmethod
    def east_is_east_of_west(cls, value: float, info: Any) -> float:
        if "west_deg_east" in info.data and value <= info.data["west_deg_east"]:
            raise ValueError("east_deg_east must be greater than west_deg_east; split antimeridian AOIs")
        return value

    @field_validator("north_deg")
    @classmethod
    def north_is_not_south(cls, value: float, info: Any) -> float:
        if "south_deg" in info.data and value <= info.data["south_deg"]:
            raise ValueError("north_deg must be greater than south_deg")
        return value


class RegionOfInterest(BaseModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    bounds: BoundingBox
    analysis_margin_m: float = Field(default=1000, ge=0, le=100000)
    local_projection: str | None = None


class CoverageStatus(str, Enum):
    available = "available"
    partial = "partial"
    unavailable = "unavailable"
    unknown = "unknown"


class FreshnessState(str, Enum):
    up_to_date = "up_to_date"
    update_available = "update_available"
    unable_to_verify = "unable_to_verify"
    downloading = "downloading"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class AssetLifecycleState(str, Enum):
    discovered = "discovered"
    selected = "selected"
    downloading = "downloading"
    downloaded = "downloaded"
    validating = "validating"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class DatasetCategory(str, Enum):
    elevation = "elevation"
    imagery = "imagery"
    spectral = "spectral"
    thermal = "thermal"
    geology = "geology"
    environment = "environment"


class DatasetCoverage(BaseModel):
    status: CoverageStatus
    percent_of_aoi: float = Field(ge=0, le=100)
    valid_percent: float | None = Field(default=None, ge=0, le=100)
    footprint: BoundingBox | None = None


class SourceSpatialMetadata(BaseModel):
    """Source spatial semantics retained before canonical conversion."""
    latitude_type: str | None = None
    longitude_direction: str | None = None
    longitude_domain: str | None = None
    horizontal_datum: str | None = None
    vertical_datum: str | None = None
    body_name: str | None = None
    radii_m: list[float] | None = Field(default=None, min_length=2, max_length=3)
    projection_wkt: str | None = None


class DatasetRecord(BaseModel):
    id: UUID
    source: Literal["pds", "ode", "usgs", "local"]
    product_id: str
    version: str | None = None
    instrument: str | None = None
    category: DatasetCategory
    processing_level: str | None = None
    resolution_m_per_px: float | None = Field(default=None, gt=0)
    coverage: DatasetCoverage
    freshness: FreshnessState
    asset_state: AssetLifecycleState | None = None
    acquired_at: datetime | None = None
    download_url: HttpUrl | None = None
    provenance_url: HttpUrl | None = None
    source_spatial_metadata: SourceSpatialMetadata | None = None
    limitations: list[str] = Field(default_factory=list)


class DatasetQuery(BaseModel):
    roi: RegionOfInterest | None = None
    categories: list[DatasetCategory] = Field(default_factory=list)
    freshness: list[FreshnessState] = Field(default_factory=list)
    coverage_status: list[CoverageStatus] = Field(default_factory=list)


class DatasetAsset(BaseModel):
    id: UUID
    dataset_id: UUID
    kind: Literal["raw", "validated", "processed", "derived"]
    relative_path: str
    checksum_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    state: AssetLifecycleState
    content_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    created_at: datetime


class AcquisitionRequest(BaseModel):
    """Analyzer-to-cache request; never contains an arbitrary filesystem path."""
    dataset: DatasetRecord
    expected_checksum_sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    maximum_size_bytes: int = Field(gt=0)
    allow_cached: bool = True


class AcquisitionResult(BaseModel):
    dataset: DatasetRecord
    asset: DatasetAsset | None = None
    reused_cached_asset: bool = False
    warnings: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None


class JobStage(str, Enum):
    queued = "queued"
    discovery = "discovery"
    selection = "selection"
    downloading = "downloading"
    preprocessing = "preprocessing"
    harmonization = "harmonization"
    terrain = "terrain"
    science = "science"
    completed = "completed"
    failed = "failed"


class AnalysisJob(BaseModel):
    id: UUID
    mission_id: UUID
    stage: JobStage
    progress_percent: int = Field(ge=0, le=100)
    message: str
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class DatasetRefreshJob(BaseModel):
    id: UUID
    dataset_id: UUID
    state: AssetLifecycleState
    progress_percent: int = Field(ge=0, le=100)
    message: str
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class Mission(BaseModel):
    id: UUID
    name: str
    objective: str | None = None
    roi: RegionOfInterest | None = None
    base: LonLat | None = None
    destination: LonLat | None = None
    active_analysis_id: UUID | None = None
    created_at: datetime


class CreateMissionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    objective: str | None = Field(default=None, max_length=500)
    roi: RegionOfInterest | None = None
    base: LonLat | None = None
    destination: LonLat | None = None


class CreateAnalysisRequest(BaseModel):
    mission_id: UUID
    roi: RegionOfInterest
    objective: str = Field(min_length=1, max_length=500)


class LocalGridMetadata(BaseModel):
    """Metric-grid metadata for safe routing and DEM-derived 3D rendering."""
    crs_wkt: str
    affine_transform: list[float] = Field(min_length=6, max_length=6)
    pixel_size_x_m: float = Field(gt=0)
    pixel_size_y_m: float = Field(gt=0)
    origin_x_m: float
    origin_y_m: float
    north_up: bool
    raster_rows_increase_south: bool
    body_name: str
    horizontal_datum: str | None = None
    vertical_datum: str | None = None


class ProcessingProvenance(BaseModel):
    recipe_version: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    source_asset_ids: list[UUID] = Field(default_factory=list)
    output_checksum_sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    generated_at: datetime | None = None


class ProcessedLayer(BaseModel):
    id: UUID
    kind: Literal["imagery", "elevation", "slope", "roughness", "hazard", "science", "coverage", "validity", "source"]
    uri: str
    bounds: BoundingBox
    resolution_m_per_px: float = Field(gt=0)
    valid_percent: float = Field(ge=0, le=100)
    units: str
    dataset_ids: list[UUID]
    grid: LocalGridMetadata | None = None
    provenance: ProcessingProvenance | None = None
    availability: CoverageStatus = CoverageStatus.available
    limitations: list[str] = Field(default_factory=list)
    style_hint: dict[str, Any] = Field(default_factory=dict)


class ScienceEvidence(BaseModel):
    dataset_id: UUID
    layer_id: UUID | None = None
    statement: str
    measured: bool
    source_uri: str | None = None
    limitations: list[str] = Field(default_factory=list)


class ScienceTarget(BaseModel):
    id: UUID
    location: LonLat
    title: str
    objective_category: str
    relevance_score: float = Field(ge=0, le=1)
    confidence: Literal["low", "medium", "high", "unknown"]
    rank_explanation: str | None = None
    evidence: list[ScienceEvidence]


class RegionalAnalysisResult(BaseModel):
    id: UUID
    mission_id: UUID
    roi: RegionOfInterest
    projection_wkt: str
    grid: LocalGridMetadata | None = None
    datasets: list[DatasetRecord]
    layers: list[ProcessedLayer]
    science_targets: list[ScienceTarget]
    warnings: list[str] = Field(default_factory=list)
    processing_provenance: list[ProcessingProvenance] = Field(default_factory=list)
    analysis_version: str


class RoutePreset(str, Enum):
    safest = "safest"
    shortest = "shortest"
    balanced = "balanced"
    science_focused = "science_focused"


class UnknownTerrainPolicy(str, Enum):
    exclude = "exclude"
    penalize = "penalize"


class WeightPreferences(BaseModel):
    distance: float = Field(default=1, ge=0, le=10)
    slope: float = Field(default=2, ge=0, le=10)
    roughness: float = Field(default=2, ge=0, le=10)
    elevation_gain: float = Field(default=1, ge=0, le=10)
    hazard: float = Field(default=3, ge=0, le=10)
    science: float = Field(default=1, ge=0, le=10)
    confidence: float = Field(default=2, ge=0, le=10)


class MissionConstraints(BaseModel):
    max_slope_deg: float = Field(default=12, gt=0, le=45, description="Prototype assumption, not NASA EVA guidance")
    max_distance_m: float | None = Field(default=None, gt=0)
    max_duration_min: float | None = Field(default=None, gt=0)
    max_elevation_gain_m: float | None = Field(default=None, gt=0)
    traversal_speed_m_per_min: float = Field(default=50, gt=0, description="Prototype assumption")
    examination_time_per_target_min: float = Field(default=0, ge=0)
    max_target_count: int | None = Field(default=None, ge=1)
    return_to_base: bool = True
    reserve_fraction: float = Field(default=.2, ge=0, lt=1)
    unknown_terrain_policy: UnknownTerrainPolicy = UnknownTerrainPolicy.exclude
    required_target_ids: list[UUID] = Field(default_factory=list)


class BlockedArea(BaseModel):
    id: UUID | None = None
    bounds: BoundingBox
    reason: str = Field(min_length=1, max_length=500)


class RouteRequest(BaseModel):
    mission_id: UUID
    analysis_id: UUID
    analysis_version: str
    start: LonLat
    destination: LonLat
    preset: RoutePreset | None = None
    preferences: WeightPreferences = Field(default_factory=WeightPreferences)
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)
    blocked_areas: list[BlockedArea] = Field(default_factory=list)


class RouteMetrics(BaseModel):
    distance_m: float
    estimated_duration_min: float
    max_slope_deg: float | None = None
    elevation_gain_m: float | None = None
    science_value: float | None = Field(default=None, ge=0, le=1)
    confidence: Literal["low", "medium", "high", "unknown"]


class RouteSegment(BaseModel):
    from_location: LonLat
    to_location: LonLat
    target_id: UUID | None = None
    distance_m: float
    estimated_duration_min: float


class ElevationProfilePoint(BaseModel):
    distance_m: float = Field(ge=0)
    elevation_m: float | None = None
    valid: bool


class RouteProvenance(BaseModel):
    analysis_version: str
    formula_version: str
    layer_ids: list[UUID] = Field(default_factory=list)
    heuristic_disclosure: str | None = None


class ConstraintConflict(BaseModel):
    code: str
    message: str
    affected_target_ids: list[UUID] = Field(default_factory=list)


class RouteAlternative(BaseModel):
    id: UUID
    label: str
    geometry: list[LonLat] = Field(default_factory=list)
    metrics: RouteMetrics | None = None
    warnings: list[str] = Field(default_factory=list)


class RouteResult(BaseModel):
    id: UUID
    feasible: bool
    analysis_id: UUID | None = None
    analysis_version: str | None = None
    request_version: str | None = None
    geometry: list[LonLat] = Field(default_factory=list)
    waypoints: list[LonLat] = Field(default_factory=list)
    metrics: RouteMetrics | None = None
    segments: list[RouteSegment] = Field(default_factory=list)
    elevation_profile: list[ElevationProfilePoint] = Field(default_factory=list)
    alternatives: list[RouteAlternative] = Field(default_factory=list)
    target_ids: list[UUID] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    constraint_conflicts: list[str] = Field(default_factory=list)
    conflict_details: list[ConstraintConflict] = Field(default_factory=list)
    provenance: RouteProvenance | None = None


class ReplanRequest(BaseModel):
    original_route_id: UUID
    analysis_id: UUID
    original_request_version: str
    blocked_areas: list[BlockedArea] = Field(min_length=1)


class NavigationState(BaseModel):
    position: LonLat
    heading_deg_clockwise_from_north: float = Field(ge=0, lt=360)
    next_waypoint: LonLat | None = None
    relative_turn_deg: float | None = Field(default=None, ge=-180, lt=180)
    distance_to_waypoint_m: float | None = Field(default=None, ge=0)
    remaining_distance_m: float | None = Field(default=None, ge=0)


class NavigationGuideRequest(BaseModel):
    route_id: UUID
    state: NavigationState


class NavigationInstruction(BaseModel):
    message: str
    relative_turn_deg: float | None = Field(default=None, ge=-180, lt=180)
    distance_to_waypoint_m: float | None = Field(default=None, ge=0)
    remaining_distance_m: float | None = Field(default=None, ge=0)


class AssistantToolName(str, Enum):
    analysis_start = "analysis_start"
    analysis_status = "analysis_status"
    analysis_result = "analysis_result"
    target_lookup = "target_lookup"
    route_create = "route_create"
    route_replan = "route_replan"
    dataset_status = "dataset_status"
    navigation_guide = "navigation_guide"


class AssistantToolCall(BaseModel):
    id: str
    name: AssistantToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["completed", "failed", "rejected"]
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class AssistantCitation(BaseModel):
    id: str
    source_uri: str
    title: str | None = None
    document_id: UUID | None = None
    excerpt: str | None = None


class AssistantAction(BaseModel):
    """Verified UI instruction derived from a tool result, never LLM-computed geometry."""
    type: Literal["focus_target", "focus_route", "focus_roi", "select_layer"]
    payload: dict[str, Any]


class AssistantRequest(BaseModel):
    mission_id: UUID
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class AssistantResponse(BaseModel):
    message: str
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)
    citations: list[AssistantCitation] = Field(default_factory=list)
    actions: list[AssistantAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RagDocument(BaseModel):
    id: UUID
    source_uri: str
    content_hash: str
    chunk_index: int = Field(ge=0)
    indexed_at: datetime


class OfflinePackageRequest(BaseModel):
    include_raw_assets: bool = False
    include_rag_index: bool = False


class OfflinePackageStatus(BaseModel):
    mission_id: UUID
    state: Literal["not_prepared", "preparing", "ready", "failed"]
    size_bytes: int | None = Field(default=None, ge=0)
    missing_requirements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
