# MarsNav

MarsNav is a Martian Marswalk planner for NASA Space Apps 2026. Given a region of Mars it retrieves real planetary data, derives terrain layers, and (as each part lands) plans walking routes and science stops within life-support limits. It is a scientific planning prototype, not a certified EVA system.

## What works today

| Area | State |
|---|---|
| Shared contracts (Python and TypeScript) | Defined and mirrored; see [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md) |
| Terrain analysis from the MOLA 463 m global DEM | Working end to end: `POST /api/v1/analyses`, poll, fetch result |
| Terrain bundle for routing and the map | Specified in [`docs/TERRAIN_CONTRACT.md`](docs/TERRAIN_CONTRACT.md) and produced by the analyzer |
| ODE product search (metadata parser) | Verified against recorded live replies |
| Dashboard and map UI | Working on mock data |
| Routing, caching and downloads, science targets, assistant | See the member task documents; not covered by the analyzer |

[`docs/ANALYZER_STATUS.md`](docs/ANALYZER_STATUS.md) lists exactly what is implemented, partial and unsupported in the analyzer, with the verified data sources. Coarse global elevation supports broad planning only; it cannot show rocks or small obstacles.

## Repository layout

```
backend/    FastAPI app (app/analyzer, app/connectors, app/routing, app/data_services, ...) and tests
frontend/   React + TypeScript dashboard and map (src/features/*, src/store, src/api, src/types)
docs/       Specifications, contracts and member task documents
data/       Local data folders (contents are not committed)
```

## Quick start

1. Copy `.env.example` to `.env` and set local values.
2. `docker compose up -d db` starts PostgreSQL for development.
3. Backend: `cd backend; python -m venv .venv; .venv\Scripts\activate; pip install -e '.[dev]'; uvicorn app.main:app --reload`.
4. Frontend: `cd frontend; npm install; npm run dev`.

The FastAPI OpenAPI document is available at `/docs`; it is the executable complement to `docs/API_CONTRACTS.md`.

### Try the analysis endpoint

```bash
curl -X POST http://localhost:8000/api/v1/analyses -H "Content-Type: application/json" -d '{
  "mission_id": "00000000-0000-0000-0000-000000000001",
  "roi": {"name": "Jezero", "bounds": {"west_deg_east": 77.2, "south_deg": 18.2, "east_deg_east": 77.6, "north_deg": 18.6}, "analysis_margin_m": 1000},
  "objective": "terrain overview"}'
# then: GET /api/v1/analyses/{id}  and  GET /api/v1/analyses/{id}/result
```

The analyzer reads only the rows it needs from the public USGS MOLA file over HTTP; no API key is required. Limits are set by `ANALYZER_MAX_AREA_KM2` and `ANALYZER_MAX_DOWNLOAD_BYTES`.

## Tests

- Backend: `cd backend; python -m pytest -q`. Add `RUN_REAL_DATA=1` to also read the live MOLA file (about 2.6 MB per window).
- Frontend: `cd frontend; npm run build` and `npm test`.

## Coordinates and units

Latitude is planetocentric degrees; longitude is east-positive in `[-180, 180)`; distances are metres, slopes degrees, durations minutes. Source products keep their original conventions and are converted at ingestion. See [`docs/COORDINATE_CONVENTIONS.md`](docs/COORDINATE_CONVENTIONS.md).

## Read before coding

[`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md), [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md), and your document in [`docs/MEMBER_TASKS`](docs/MEMBER_TASKS).

## Repository rules

One FastAPI app, one frontend, and one source of truth for contracts. Keep downloaded products and generated rasters out of Git. Branch names start with the member name and name the feature (for example `aakash/analyzer-terrain-pipeline`); open a PR into `main`; see `CONTRIBUTING.md`.
