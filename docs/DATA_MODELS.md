# Shared data models

Canonical transport and inter-module types live in `backend/app/schemas/contracts.py`; frontend mirrors are in `frontend/src/types/contracts.ts`. OpenAPI is generated from the Pydantic schemas. IDs are UUIDs; dates are ISO-8601 UTC; enumerations must not be replaced by UI strings.

| Model | Key semantics |
|---|---|
| `LonLat`, `BoundingBox`, `RegionOfInterest` | Normative planetocentric/east-positive conventions; AOIs cannot cross the antimeridian. |
| `DatasetRecord`, `DatasetCoverage`, `DatasetAsset` | Product identity/version, coverage, source spatial semantics, freshness/limitations, and checksummed local asset identity. |
| `AcquisitionRequest`, `AcquisitionResult`, `DatasetRefreshJob` | Analyzer-cache handoff and durable asset lifecycle; no arbitrary local paths or fabricated availability. |
| `AnalysisJob` | Durable stage and percent; `failed` includes a safe user-facing message and code. |
| `LocalGridMetadata`, `ProcessedLayer`, `ProcessingProvenance` | Metric local CRS/WKT, affine/orientation/pixel metadata, layer reference, validity and reproducible processing; never inline rasters. |
| `ScienceTarget`, `ScienceEvidence` | Coordinates only from a record/layer; `measured` distinguishes observation from heuristic relevance. |
| `MissionConstraints`, `WeightPreferences`, `BlockedArea` | Constraints are non-negotiable; unknown-terrain policy is explicit; weights are normalized/validated by routing. |
| `RouteResult`, `RouteMetrics`, `ElevationProfilePoint`, `RouteProvenance` | Feasible result has geometry/metrics/segments/elevation profile; infeasible has no geometry and structured conflicts; both retain analysis/formula versions. |
| `NavigationState`, `NavigationInstruction` | Simulated position/heading and derived waypoint-relative guidance. |
| `AssistantRequest/Response`, `AssistantToolCall`, `AssistantCitation`, `AssistantAction` | Text plus audited allowlisted tool calls, retrieved citations, verified UI actions, and warnings. |
| `OfflinePackageRequest/Status` | Explicit preparation state and missing local dependencies for a mission. |

Confidence is `high`, `medium`, `low`, or `unknown`; it is an evidence/coverage assessment, never a safety certification. Nullable metrics mean unavailable/not computable, not zero. Percentages are `[0,100]`, scores `[0,1]`, and no-data/masks are retained in a processed layer rather than coerced to numeric values.

`RegionalAnalysisResult` contains its UUID, ROI, selected datasets, optional canonical local grid, processed layers, targets, warnings, and processing provenance. `ProcessedLayer.grid` is required whenever a consumer needs metric-grid operations or DEM-derived 3D. Unavailable data stays explicit through coverage and limitations fields.
