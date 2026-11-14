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
| Assistant tools | `ai/tools/registry.py`, `ai/assistant.py`, `api/routes/assistant.py` | Validated tools (analysis start/status/result, target lookup, dataset status); deterministic request planner; answers copied from tool results; `POST /assistant/messages` |
| Routing terrain access | `analyzer/integration/routing_terrain.py`, `api/routes/analyses.py` | Verified arrays, grid, lon/lat to cell lookup, version checking; HTTP `terrain.npz` download |
| Map display package | `analyzer/publishing/map_display.py`, `api/routes/analyses.py` | Layer images (PNG) and a display DEM in the map module's format; frontend client in `frontend/src/api/analysis.ts` |
| Base imagery | `frontend/src/features/mars-map/BaseImagery.ts` | Mars Trek tiles composed into the map's angular coordinate system; tile maths tested; needs network access at run time (the map still works without it, with no imagery) |
| Analysis jobs | `analyzer/orchestration/`, `api/routes/analyses.py` | Create, poll, result; one heavy job at a time; de-duplication; saved state; interrupted-job recovery |

## Verified sources

| Source | URL | Verified |
|---|---|---|
| ODE REST | https://oderest.rsl.wustl.edu/live2 | Manual V2.1.6 read; example queries returned HiRISE product metadata; longitudes positive east 0-360 |
| MOLA global DEM | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif | Header read: 46080 x 23040, int16, uncompressed, one row per strip, contiguous; range requests supported; live window read over Jezero |
| NASA Mars Trek tiles | https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/ | WMTS capabilities read; geographic tiles, 256 px, top-left (-180, 90), zoom 0-7, EPSG:104905; live tiles fetched for zoom 0 and a Jezero zoom-7 tile; zoom 8 returns 404. Context imagery only, not elevation |
| USGS catalog | https://fdp.astrogeology.usgs.gov/fdp/mars/ | Lists the MOLA DEM (463 m); download links are not present in the page HTML |

Not stated by the sources and therefore not claimed: the MOLA vertical unit and datum, and the units of ODE `Map_scale`.

## Partial

- **Analysis result:** terrain only. No science layers or targets are produced; the result carries a warning saying so.
- **Acquisition:** reads directly from the source through an injectable fetcher; it does not use the cache or download service yet.
- **Region expansion:** `expand_region` exists and is tested, but nothing calls it until routing reports boundary-limited failures.
- **Footprints:** ODE footprints are reduced to bounding boxes because the shared contract has no polygon footprint.

## Not implemented

- Science objectives and target extraction (CRISM spectral, THEMIS thermal, geology).
- Multi-resolution fusion (only one elevation source is supported).
- HRSC and HiRISE DTM readers; PDS Search API adapter.
- Raster formats other than the MOLA layout (GeoTIFF/PDS IMG readers, reprojection).
- Job cancellation (the job contract has no cancelled stage).
- Mission and route orchestration, and the optimizer (owned by routing).
- Language-model planning (Ollama) and local RAG: the assistant is deterministic and has no model or retrieval yet. Route, replan and navigation tools answer that routing is not connected.
- Frontend chat: the dashboard's assistant drawer still uses its mock; it is not wired to `POST /assistant/messages`.
- Higher-resolution imagery (CTX, HiRISE) as a map base; the base layer is the 232 m Viking colour mosaic.

## Limits and settings

`ANALYZER_MAX_AREA_KM2` (default 2500) and `ANALYZER_MAX_DOWNLOAD_BYTES` (default 64 MiB), read from the environment through `app/core/config.py`.

## Testing

`cd backend && python -m pytest -q` runs the offline tests. `RUN_REAL_DATA=1 python -m pytest -q` also reads the live MOLA file (about 2.6 MB per window).
