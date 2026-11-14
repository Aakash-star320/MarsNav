# Contract change log

## 0.2.4 draft — assistant tool analysis_start

Additive. `AssistantToolName` gains `analysis_start` so the assistant can start an analysis for an area through the same validated tool path; Python and TypeScript mirrors updated together.

## 0.2.3 draft — routing terrain access

Additive. `load_routing_terrain` (in-process) and `GET /analyses/{id}/terrain.npz?analysis_version=` (HTTP) give routing the verified terrain arrays with version checking; see [`TERRAIN_CONTRACT.md`](TERRAIN_CONTRACT.md). No existing field changed.

## 0.2.2 draft — map display package

Additive. New Python models `MapPackage`, `MapLayerEntry`, `DemPayload` and `DemProjection` (`app/schemas/map_display.py`) mirror the display types the map module already defines in `frontend/src/features/mars-map/types.ts`; no TypeScript change was needed. New endpoints `GET /analyses/{id}/map` and `GET /analyses/{id}/layers/{kind}.png`. See [`TERRAIN_CONTRACT.md`](TERRAIN_CONTRACT.md).

## 0.2.1 draft — terrain artifact layer kinds

Additive and backwards compatible. `ProcessedLayer.kind` gains `validity` (boolean valid-data mask) and `source` (per-cell source product index) so routing and the map can consume aligned analyzer terrain. The terrain file layout is specified in [`TERRAIN_CONTRACT.md`](TERRAIN_CONTRACT.md). Python and TypeScript mirrors are updated together; no existing field changed.

## 0.2.0 draft — cross-team implementation contracts

This additive contract update aligns the original scaffold with the full MarsNav feature set. It is intentionally limited to shared models, endpoint skeletons, frontend mirrors, and documentation; it does not implement analyzer, cache, routing, map, dashboard, or AI behavior.

### Required handoffs

| Producer | Consumer | Contract |
|---|---|---|
| Data/cache | Analyzer | `AcquisitionRequest` -> `AcquisitionResult`, `DatasetAsset`, `DatasetRefreshJob` |
| Analyzer | Routing and map | `RegionalAnalysisResult`, `ProcessedLayer`, `LocalGridMetadata`, `ProcessingProvenance` |
| Routing | Dashboard, map, assistant | `RouteResult`, `RouteSegment`, `RouteAlternative`, `ConstraintConflict`, `RouteProvenance` |
| AI | Dashboard and map | `AssistantResponse`, typed `AssistantToolCall`, `AssistantCitation`, `AssistantAction` |
| Data/cache | Dashboard | `OfflinePackageRequest`, `OfflinePackageStatus` |

### Compatibility and implementation rules

- Existing fields remain available. New optional result metadata is additive.
- `RouteRequest.analysis_version` and `ReplanRequest.original_request_version` are now required to prevent use of silently replaced analysis data.
- `BoundingBox` now rejects east <= west, including antimeridian-crossing AOIs. Callers must split those AOIs before a request.
- `ProcessedLayer.grid` may be absent for display-only layers. Routing and DEM-derived 3D must require it when metric grid operations are needed.
- Assistant tool names are an allowlist. Tool arguments/results and map/dashboard actions must be derived from validated service results, not calculated by the model.
- `relative_path` is an internal cache identifier. It must never be returned as an arbitrary file-serving URL.

Before implementing a consumer, use the Pydantic model as the source of truth and mirror any approved new fields in `frontend/src/types/contracts.ts`. Regenerate and review OpenAPI in CI before merge.
