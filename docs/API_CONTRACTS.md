# API contracts

Prefix: `/api/v1`; JSON; UUID paths; validation errors use FastAPI's standard `422` detail. All responses may return `400` invalid state, `404` resource absent, `409` conflicting active data/version, `422` schema validation, or `503` unavailable remote/local dependency. API owners must define error codes/messages before implementation.

| Method / path | Request -> response | Owner |
|---|---|---|
| `GET /health` | -> service state | Integration |
| `POST /missions` / `GET /missions/{id}` | mission setup -> mission state | Data/cache |
| `POST /missions/{id}/offline-package` | `OfflinePackageRequest` -> `OfflinePackageStatus` (202) | Data/cache |
| `GET /missions/{id}/offline-package` | -> `OfflinePackageStatus` | Data/cache |
| `POST /analyses` | `CreateAnalysisRequest` -> `AnalysisJob` (202) | Analyzer/AI |
| `GET /analyses/{id}` | -> `AnalysisJob` | Analyzer/AI |
| `GET /analyses/{id}/result` | -> `RegionalAnalysisResult` / 409 while pending | Analyzer/AI |
| `GET /datasets`, `GET /datasets/{id}` | typed category/freshness query -> `DatasetRecord[]` | Data/cache |
| `POST /datasets/{id}/refresh` | -> `DatasetRefreshJob` (202) | Data/cache |
| `POST /routes` | `RouteRequest` -> `RouteResult` | Routing |
| `POST /routes/{id}/replan` | `ReplanRequest` -> `RouteResult` | Routing |
| `POST /navigation/guide` | `NavigationGuideRequest` -> `NavigationInstruction` | Routing |
| `POST /assistant/messages` | `AssistantRequest` -> `AssistantResponse` | Analyzer/AI |
| `GET /assistant/status` | -> `{mode, model}` | Analyzer/AI |

`POST /analyses` is asynchronous because discovery/download/processing may take time. Its result only references artifacts already persisted locally. `POST /routes` is synchronous for prototype-sized grids; it returns `feasible:false` with empty geometry and conflicts rather than an error for a valid no-route condition. Route/replan requests carry analysis/version identifiers so active data cannot be silently replaced. Dataset refresh uses a dataset-specific lifecycle job, never an analysis job.

Dataset filtering and all map geometry are typed. AOIs use the canonical `BoundingBox`; endpoints may not accept free-form map geometry. Offline-package preparation reports missing requirements rather than claiming that unavailable assets are prepared.

Frontend calls are centralized under `frontend/src/api`; mock handlers reproduce exact JSON bodies. FastAPI Pydantic code is source of truth; export `backend/openapi.json` in CI and compare it with frontend types before merge.
