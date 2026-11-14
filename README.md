# MarsNav

MarsNav is a Martian Marswalk planner for NASA Space Apps 2026. Given a region of Mars it retrieves real planetary data, derives terrain layers, and (as each part lands) plans walking routes and science stops within life-support limits. It is a scientific planning prototype, not a certified EVA system.

## What works today

| Area | State |
|---|---|
| Terrain analysis from the MOLA 463 m global DEM | Working end to end: draw a region, get real elevation, slope, roughness and steep-terrain layers and statistics |
| Hydrated-mineral candidates (CRISM) | Heuristic candidates with evidence and a map overlay; rule and limits in [`docs/SCIENCE_CRISM.md`](docs/SCIENCE_CRISM.md). They are screens of summary parameters, not identified minerals |
| Dashboard map | Zoomable and pannable Mars map (NASA Mars Trek imagery), analysis layers placed by their geographic bounds, pins for start, destination, base, waypoints and targets |
| 2D / 3D | 3D shows the real elevation as a solid block with the imagery draped over it; it reads the visible area by itself if nothing has been analysed |
| Routes | Real routes on the analysed terrain from the routing service: shortest / safest / balanced comparison, waypoints, a base point for the return trip, obstacles with replanning, an elevation profile and navigation guidance |
| Science missions | Real mission planner: picks the analysis' science targets that fit the oxygen budget, plans every leg and says why a target was left out |
| Assistant | Docked chat panel with result cards and "show on map" actions. It uses a hosted Gemma model when `GEMMA_MODEL` and `GEMMA_API_KEY` are set and a rule-based assistant otherwise; the model can only call read-only, validated tools |
| Contracts | Python and TypeScript mirrors; see [`docs/API_CONTRACTS.md`](docs/API_CONTRACTS.md) and [`docs/CONTRACT_CHANGELOG.md`](docs/CONTRACT_CHANGELOG.md) |
| Not built | Download service and cache, the database-backed mission store, document search (RAG), other science objectives, finer terrain than 463 m (see [`docs/ANALYZER_STATUS.md`](docs/ANALYZER_STATUS.md)) |

Everything runs without an API key except the optional Gemma assistant. Elevation, imagery and spectral data are read directly from public NASA and USGS servers, so an internet connection is needed. Coarse global elevation supports broad planning only: it cannot show rocks or small obstacles, slopes are not a safety assessment, and walking speed, oxygen and slope limits are prototype assumptions, not NASA values.

[`backend/README.md`](backend/README.md) covers installation, configuration, equations and example requests; [`docs/ANALYZER_STATUS.md`](docs/ANALYZER_STATUS.md) lists exactly what is implemented, partial and unsupported, with the verified data sources.

## Repository layout

```
backend/    FastAPI app (app/analyzer, app/connectors, app/routing, app/data_services, ...) and tests
frontend/   React + TypeScript dashboard and map (src/features/*, src/store, src/api, src/types)
docs/       Specifications, contracts and member task documents
data/       Local data folders (contents are not committed)
```

## Quick start

Requirements: Python **3.11 or 3.12** (not 3.13 or newer), Node.js 20 or newer. PostgreSQL is not needed for the current features.

1. Optional: copy `.env.example` to `.env` at the repository root. To enable the hosted assistant set `GEMMA_MODEL` and `GEMMA_API_KEY` there; leave them empty to keep the rule-based assistant. Never commit `.env`.
2. Backend (Git Bash):
   ```bash
   cd backend
   python -m venv .venv            # on Windows: py -3.12 -m venv .venv
   source .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
   pip install -e ".[dev]"
   uvicorn app.main:app
   ```
3. Frontend (second terminal):
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
4. Open http://localhost:5173. The API documentation is at http://localhost:8000/docs.

### A short demo

1. Choose **Analyze Region**, drag a box around Jezero crater (about 20 km across) and press **Analyze Region**. You get real terrain, a statistics summary and a CRISM candidate.
2. Switch to **3D** to see the terrain as a block with the imagery draped on it, then back to **2D** (your zoom is kept).
3. Choose **Plan Route**, set a Start and a Destination inside the teal analysed box and press **Generate Routes**. Compare shortest / safest / balanced, check the elevation profile, then try **Report obstacle** to replan.
4. Choose **Plan Scientific Mission** and press **Plan Mission** (raise the oxygen hours if it does not fit).
5. Open **Ask AI assistant**: "Analyze this region", or "How steep is this area?".

Analyses are saved under `data/derived/analyses/`, so repeating a request for the same area is instant, even after a restart. Routes and mission plans are kept in memory: after restarting the backend, plan them again.

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
- Frontend: `cd frontend; npm test`, `npx tsc --noEmit` and `npm run build`.

## Coordinates and units

Latitude is planetocentric degrees; longitude is east-positive in `[-180, 180)`; distances are metres, slopes degrees, durations minutes. Source products keep their original conventions and are converted at ingestion. See [`docs/COORDINATE_CONVENTIONS.md`](docs/COORDINATE_CONVENTIONS.md).

## Read before coding

[`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md), [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md), and your document in [`docs/MEMBER_TASKS`](docs/MEMBER_TASKS).

## Repository rules

One FastAPI app, one frontend, and one source of truth for contracts. Keep downloaded products and generated rasters out of Git. Branch names start with the member name and name the feature (for example `aakash/analyzer-terrain-pipeline`); open a PR into `main`; see `CONTRIBUTING.md`.
