# Analyzer status and verified sources

Honest inventory of the analyzer. Anything not marked **Implemented** is not finished.

## Implemented (tested)

| Area | Where | Notes |
|---|---|---|
| Mars geometry | `analyzer/discovery/mars_geometry.py` | Mars mean radius 3389.5 km; haversine; local metric frame; antimeridian and polar rejection |
| Region planner | `analyzer/discovery/region_planner.py` | Analyze, route (buffer, budget ellipse, impossible-budget rejection), mission (time/speed bound, return base, selection-area intersection), bounded expansion (1.5x, three attempts) |
| Product selection | `analyzer/selection/selector.py` | Deterministic greedy coverage per category; reasons for rejected products; categories never substituted |
| Terrain derivatives | `analyzer/preprocessing/terrain.py` | Slope, signed directional edge grade, roughness; missing data never creates gradients |
| Terrain bundle | `analyzer/preprocessing/terrain_bundle.py`, `docs/TERRAIN_CONTRACT.md` | Aligned arrays, atomic write, checksum, verification on load |
| Cache keys | `analyzer/validation/cache_keys.py` | Stable hashes for raw, processed and analysis keys |
| ODE REST adapter | `connectors/ode/ode_rest.py` | Query builder and parser, verified against recorded live replies |
| MOLA 463 m DEM reader | `connectors/usgs/mola.py` | Windowed reads by HTTP range request; verified against the live file |
| Science objective: hydrated minerals | `analyzer/science/`, `connectors/pds/crism_mtrdr.py` | CRISM MTRDR summary-parameter bands read by range request; heuristic candidates with evidence; rule and limits in [`SCIENCE_CRISM.md`](SCIENCE_CRISM.md) |
| Dashboard Analyze Region | `frontend/src/store/dashboardStore.ts`, `features/dashboard/*` | Calls the real analysis: real statistics, elevation / slope / steep-terrain / spectral layers, CRISM candidates with evidence; cancel works; failures are shown, never replaced by simulated results. Routes, missions and the other layers remain simulated and are labelled |
| Science overlay and cancellation | `analyzer/publishing/science_layer.py`, `POST /analyses/{id}/cancel` | CRISM evidence raster served as a map layer on its own grid; queued or running jobs can be cancelled at a stage boundary and their partial files are removed |
| Benchmarks and README | `scripts/benchmark_analyzer.py`, [`BENCHMARKS.md`](BENCHMARKS.md), `backend/README.md` | Offline and live timings measured; install, configuration, equations, examples and limits documented |
| Assistant tools | `ai/tools/registry.py`, `ai/assistant.py`, `api/routes/assistant.py` | Validated tools (analysis start/status/result, target lookup, dataset status); deterministic request planner; answers copied from tool results; `POST /assistant/messages` |
| Routing terrain access | `analyzer/integration/routing_terrain.py`, `api/routes/analyses.py` | Verified arrays, grid, lon/lat to cell lookup, version checking; HTTP `terrain.npz` download |
| Map display package | `analyzer/publishing/map_display.py`, `api/routes/analyses.py` | Layer images (PNG) and a display DEM in the map module's format; frontend client in `frontend/src/api/analysis.ts` |
| Base imagery | `frontend/src/features/mars-map/BaseImagery.ts` | Mars Trek tiles composed into the map's angular coordinate system; tile maths tested; needs network access at run time (the map still works without it, with no imagery) |
| Analysis jobs | `analyzer/orchestration/`, `api/routes/analyses.py` | Create, poll, result; one heavy job at a time; de-duplication; saved state; interrupted-job recovery |
| Objective registry | `analyzer/science/objectives.py`, `terrain_objectives.py`, `api/routes/objectives.py` | `GET /objectives`; hydrated minerals plus flat safe sites and high vantage points detected in the MOLA terrain arrays, each target with measured evidence, heuristic rule and limits |
| Availability check | `analyzer/discovery/availability.py`, `api/routes/availability.py` | `POST /objectives/check`: asks ODE which instruments cover the area for a free-text objective; reports data that exists but cannot be analysed yet, and never claims absence when the catalog is unreachable |
| Data cap | `analyzer/validation/data_budget.py`, `GET /data-budget` | Per-analysis and per-session byte limits applied before any read |
| Routing service | `routing/` (engine, `api_service.py`), `api/routes/routing.py` | Deterministic A* on the analysed terrain; `POST /routes`, `GET /routes/{id}`, `POST /routes/{id}/replan`, `POST /navigation/guide`; waypoints, base point, blocked areas, comparison routes with elevation profiles; routes held in memory |
| Mission planner | `routing/mission_planner.py`, `api/routes/mission_plans.py` | `POST /mission-plans`: greedy selection of the analysis' science targets inside the oxygen budget, every leg planned by the routing engine, excluded targets listed with reasons |
| Hosted-model assistant | `ai/llm/gemma.py`, `ai/llm_assistant.py`, `api/routes/assistant.py` | Gemma over the Generative Language REST API when `GEMMA_MODEL` and `GEMMA_API_KEY` are set; JSON tool protocol, read-only tools, validated arguments, analysis ids must come from the request or a tool result, one repair attempt, bounded loop, rule-based fallback with a warning. Not tested against a real model |
| Dashboard map and 3D | `frontend/src/features/dashboard/MapCanvas.tsx`, `features/mars-map/Terrain3D.tsx` | Zoomable Leaflet map with an SVG overlay in canvas pixels; 3D block with imagery, side walls and hillshade lighting; 3D reads the visible area when nothing is analysed |
| Dashboard chat | `frontend/src/features/dashboard/ChatPanel.tsx`, `api/assistant.ts` | Docked panel with tool-step chips, result cards and "show on map" actions; commands run the checked UI actions, questions go to the assistant service |

## Verified sources

| Source | URL | Verified |
|---|---|---|
| ODE REST | https://oderest.rsl.wustl.edu/live2 | Manual V2.1.6 read; example queries returned HiRISE product metadata; longitudes positive east 0-360 |
| MOLA global DEM | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif | Header read: 46080 x 23040, int16, uncompressed, one row per strip, contiguous; range requests supported; live window read over Jezero |
| NASA Mars Trek tiles | https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/ | WMTS capabilities read; geographic tiles, 256 px, top-left (-180, 90), zoom 0-7, EPSG:104905; live tiles fetched for zoom 0 and a Jezero zoom-7 tile; zoom 8 returns 404. Context imagery only, not elevation |
| PDS CRISM MTRDR | https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/ | Label and ENVI header of a summary-parameter cube read (60 bands, float32, BSQ); 18 browse-product definitions fetched; range requests supported; live bands read over Jezero. The server is sometimes slow (timeouts were seen) |
| USGS catalog | https://fdp.astrogeology.usgs.gov/fdp/mars/ | Lists the MOLA DEM (463 m); download links are not present in the page HTML |

Not stated by the sources and therefore not claimed: the MOLA vertical unit and datum, and the units of ODE `Map_scale`.

## Partial

- **Analysis result:** terrain plus, for hydrated-mineral objectives, heuristic CRISM candidates. Other objectives return terrain only and say so. No science raster layer is published yet.
- **Acquisition:** reads directly from the source through an injectable fetcher; it does not use the cache or download service yet.
- **Region expansion:** `expand_region` exists and is tested, but nothing calls it until routing reports boundary-limited failures.
- **Footprints:** ODE footprints are reduced to bounding boxes because the shared contract has no polygon footprint.

## Not implemented

- Other science objectives: THEMIS thermal, geology and the other CRISM mineral families (carbonates, sulfates, mafic). Only hydrated hydroxylated-mineral candidates are implemented.
- Multi-resolution fusion (only one elevation source is supported).
- HRSC and HiRISE DTM readers; PDS Search API adapter.
- Raster formats other than the MOLA layout (GeoTIFF/PDS IMG readers, reprojection).
- Optimal ordering of mission stops (the planner is greedy), and routes that use more than the 463 m terrain.
- Local RAG (document search) and a local Ollama model: the assistant uses a hosted Gemma model when configured. The model is not offered the analysis-start or routing tools.
- Download service, cache and the database-backed mission store (owned by the data/cache task): analyses read the sources directly and save their results on disk; routes and mission plans are kept in memory.
- Higher-resolution imagery (CTX, HiRISE) as a map base; the base layer is the 232 m Viking colour mosaic.

## Limits and settings

`ANALYZER_MAX_AREA_KM2` (default 2500) and `ANALYZER_MAX_DOWNLOAD_BYTES` (default 64 MiB), read from the environment through `app/core/config.py`.

## Testing

`cd backend && python -m pytest -q` runs the offline tests. `RUN_REAL_DATA=1 python -m pytest -q` also reads the live MOLA file (about 2.6 MB per window).
