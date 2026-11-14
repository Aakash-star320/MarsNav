# MarsNav backend: analyzer

The analyzer turns a map area into real terrain layers and, for hydrated-mineral objectives, heuristic CRISM candidates. It is a scientific planning prototype, not a certified EVA system. What is implemented, partial and unsupported is listed in [`../docs/ANALYZER_STATUS.md`](../docs/ANALYZER_STATUS.md).

## Install and run

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate        # Windows; use source .venv/bin/activate elsewhere
pip install -e ".[dev]"
uvicorn app.main:app --reload                          # http://localhost:8000/docs
```

Python 3.11 to 3.13 is the declared range; the suite also passes on 3.14. No API key is needed for any source.

## Configuration

Environment variables (or a `.env` file one level up), read by `app/core/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `DATA_ROOT` | `../data` | Analysis artifacts are written to `<DATA_ROOT>/derived/analyses/<analysis_id>/` (git-ignored) |
| `ANALYZER_MAX_AREA_KM2` | 2500 | Largest area accepted; larger requests fail with `area_limit` |
| `ANALYZER_MAX_DOWNLOAD_BYTES` | 67108864 | Largest elevation read per analysis |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed browser origins |

The frontend reads `VITE_API_BASE` (default `http://localhost:8000/api/v1`).

## Supported data (verified 2026-11-14)

| Data | Source | Notes |
|---|---|---|
| Elevation | USGS MOLA global DEM, 463 m, https://planetarymaps.usgs.gov/mosaic/Mars_MGS_MOLA_DEM_mosaic_global_463m.tif | Windowed by HTTP range request; the 2.1 GB file is never downloaded. Vertical unit and datum are not stated in the file header (metres assumed) |
| Product search | ODE REST, https://oderest.rsl.wustl.edu/live2 | Manual V2.1.6; longitudes are positive east 0-360 and are converted at the boundary |
| Spectral summary parameters | PDS CRISM MTRDR, `MRO-M-CRISM-5-RDR-MPTARGETED-V1.0` | 60-band float cube per observation; three bands read by range request |
| Map imagery | NASA Mars Trek tiles, Viking MDIM 2.1 colour mosaic, 232 m/px | Context only; not elevation, no science evidence |

Supported objective: hydrated hydroxylated-mineral candidates (see [`../docs/SCIENCE_CRISM.md`](../docs/SCIENCE_CRISM.md)). Any other objective returns terrain only and says so.

## Coordinates, units and resolution

Latitude is planetocentric degrees; longitude is east-positive in [-180, 180); distances are metres, slopes degrees. Mars distances use a sphere of mean radius 3389.5 km in the region planner; terrain grids use the source sphere (3,396,190 m). The analysis grid is a local equirectangular projection with its standard parallel at the area's centre, so MOLA's longitude/latitude grid maps to metres without resampling. **Native** resolution is 463 m (MOLA) or 18/36 m (CRISM); the grid keeps the source spacing, so nothing is finer than the source. Cells carry quality flags (coarse, interpolated, slope undefined).

## Equations and rules

- Slope: `atan(sqrt((dz/dx)^2 + (dz/dy)^2))` in degrees from central differences over valid neighbours, with the real cell size; one-sided differences next to missing data; undefined where neither neighbour exists.
- Directional edge grade: `(z_next - z_current) / horizontal_distance`, signed (uphill positive).
- Roughness: standard deviation of elevation in a 3 x 3 window of valid cells (at least 60% valid).
- Route region: buffer `max(1 km, 0.5 x straight-line)`, tightened by the budget ellipse `d(A,P) + d(P,B) <= L`. Mission region: radius `speed_upper_bound x (duration - reserve - min_examination) / 2` for an out-and-back trip. Expansion by 1.5x, at most three attempts. These are simulation assumptions, not NASA constants.
- Hydrated-mineral candidate rule and its thresholds: see `docs/SCIENCE_CRISM.md`. They are documented heuristics, not published criteria.

## Example requests

```bash
curl -X POST localhost:8000/api/v1/analyses -H "Content-Type: application/json" -d '{
  "mission_id": "00000000-0000-0000-0000-000000000001", "objective": "find hydrated minerals",
  "roi": {"name": "Jezero", "bounds": {"west_deg_east": 77.30, "south_deg": 18.20, "east_deg_east": 77.65, "north_deg": 18.50}, "analysis_margin_m": 0}}'
curl localhost:8000/api/v1/analyses/{id}                 # stage and progress
curl localhost:8000/api/v1/analyses/{id}/result          # RegionalAnalysisResult (409 until completed)
curl localhost:8000/api/v1/analyses/{id}/map             # layers, display DEM, statistics, targets
curl localhost:8000/api/v1/analyses/{id}/layers/elevation.png      # also slope, roughness, science, hazard (?slope_limit_deg=)
curl "localhost:8000/api/v1/analyses/{id}/terrain.npz?analysis_version=analysis/1" -o terrain.npz   # for routing
curl -X POST localhost:8000/api/v1/analyses/{id}/cancel
```

Jobs run one at a time on a worker thread. Equivalent requests share a job, results survive a restart, and a job interrupted by a restart is recorded as failed (`interrupted`). Terrain access for routing is documented in [`../docs/TERRAIN_CONTRACT.md`](../docs/TERRAIN_CONTRACT.md).

## Tests and benchmarks

```bash
python -m pytest -q                       # offline tests
RUN_REAL_DATA=1 python -m pytest -q       # also reads the live MOLA file
python scripts/benchmark_analyzer.py      # add --real for live-source timings
```

Measured timings and memory are in [`../docs/BENCHMARKS.md`](../docs/BENCHMARKS.md).

## Known limitations

- 463 m terrain supports broad planning only. It cannot show rocks, small craters or other hazards, and slope above a limit is not a safety assessment.
- Spectral candidates are heuristic screens of summary parameters, not identified minerals, and missing coverage is never evidence of absence.
- One elevation source (MOLA); no HRSC or HiRISE terrain models and no fusion.
- The PDS server is sometimes slow; science reads fail softly with a warning.
- Imagery on the map needs internet access.
- No language-model assistant or document retrieval; the assistant is deterministic.
- Routing, caching/downloads and the mission store belong to other members; the analyzer reads sources directly until the download service exists.
