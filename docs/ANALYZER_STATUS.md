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
| Map display package | `analyzer/publishing/map_display.py`, `api/routes/analyses.py` | Layer images (PNG) and a display DEM in the map module's format; frontend client in `frontend/src/api/analysis.ts` |
| Analysis jobs | `analyzer/orchestration/`, `api/routes/analyses.py` | Create, poll, result; one heavy job at a time; de-duplication; saved state; interrupted-job recovery |

## Verified sources

| Source | URL | Verified |
|---|---|---|
| ODE REST | https://oderest.rsl.wustl.edu/live2 | Manual V2.1.6 read; example queries returned HiRISE product metadata; longitudes positive east 0-360 |
| MOLA global DEM | https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif | Header read: 46080 x 23040, int16, uncompressed, one row per strip, contiguous; range requests supported; live window read over Jezero |
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
- Assistant tools and local RAG.
- Real imagery under the map (the map module draws only the layers it is given; a base-imagery layer is not wired).

## Limits and settings

`ANALYZER_MAX_AREA_KM2` (default 2500) and `ANALYZER_MAX_DOWNLOAD_BYTES` (default 64 MiB), read from the environment through `app/core/config.py`.

## Testing

`cd backend && python -m pytest -q` runs the offline tests. `RUN_REAL_DATA=1 python -m pytest -q` also reads the live MOLA file (about 2.6 MB per window).
