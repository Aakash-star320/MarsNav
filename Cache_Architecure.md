# MarsNav caching architecture v3

The first release hardens the existing analysis service and speeds up repeat terrain reads on one host. The second release adds persistent source reuse and mission-aware retention. Browser offline support follows once a prepared mission can be verified after a restart.

## Current implementation

| Existing code | What to reuse |
|---|---|
| `backend/app/analyzer/orchestration/service.py` | Mission-scoped job deduplication, a single analysis worker, stage progress, cancellation, and job recovery. |
| `backend/app/analyzer/validation/cache_keys.py` | Stable hashing and separate raw, processed, and analysis key builders. |
| `backend/app/connectors/usgs/mola.py` | MOLA native pixel windows, halo, range fetcher, shared HTTP client and byte limits. The active terrain pipeline uses the global 463 m MOLA product. |
| `backend/app/analyzer/preprocessing/terrain_bundle.py` | Terrain manifest, checksum, grid, valid mask, source IDs, quality flags and NPZ validation. |
| `backend/app/api/routes/analyses.py` | `POST /api/v1/analyses` returns `202`. Clients poll the job and fetch the result or map. PNG endpoints already emit an ETag. |
| `frontend/src/features/mars-map/BaseImagery.ts` and `frontend/src/utils/trek.ts` | Decoded tile reuse, in-flight deduplication and coarse-first drawing. Viking's tile matrix has 42 total tiles at levels 0–2. |
| `docs/OFFLINE_AND_CACHE_SPEC.md` and `docs/DATABASE_SCHEMA.md` | PostgreSQL metadata and raster files on disk. The current mission, dataset and offline-package API scaffolds in `backend/app/api/routes/contracts.py` return `501`. |

## Identity and geographic rules

Use the repository's coordinate conventions and preserve the existing Mars projection, antimeridian split, area/download limits, and exact submitted area of interest (AOI) plus its explicit analysis margin. Let the existing reader map that area to native pixels and request the processing halo. Record the requested AOI and actual grid separately. A source-block cache may retrieve a larger block; slicing and assembly must give the analysis the same window and halo as the current direct reader.

| Object | Identity |
|---|---|
| Analysis submission and job | Scope by mission and normalized submission. Include objective, exact requested bounds, margin, and any request fields echoed in the result, such as the ROI name. Keep job UUIDs separate from reusable artifacts. |
| Source bytes | Provider, canonical resource identity, pinned source revision, byte interval or versioned native block coordinates. Store and verify a checksum of the cached bytes. |
| Computed terrain | Existing processed-region key with verified source revisions, output grid and CRS, recipe version, and all parameters that affect arrays or masks. Include native window and halo when those affect terrain computation. |
| Science | Objective and screening parameters, discovery snapshot, selected CRISM products and revisions, requested search area, recipe version. Track upstream failure separately from a verified empty search. |
| PNG and other display representations | Source artifact revision plus layer kind, display recipe version, and output-affecting parameters. The hazard variant includes the exact slope threshold used by the renderer. |
| Trek imagery | Effective tile URL, including mosaic version, tile matrix set, level, row and column. Preserve query parameters that affect the response. |

An artifact hit can supply data to a **new** mission job. It must still emit mission-specific IDs and metadata. A repeated submission for the same mission may reuse its job only if the artifacts needed to honor that job are still usable. The dashboard currently generates a new mission UUID per submission. Keep that behavior in the first release and use distinct mission IDs in cross-mission reuse tests.

## Release 1 — Correctness and repeat reads

Run one API process owning the analysis output directory and keep the existing job executor. Use the existing on-disk job layout and successful API responses. This release can run with the same local setup as the current analyzer.

### PR 1 — Harden reads and completed-job reuse

- In `backend/app/connectors/usgs/mola.py`, extend the existing fetcher. Use a bounded streamed read and accept only the requested `206` interval. Check the full `Content-Range`, body length, identity encoding, and expected representation revision when available. For MOLA, verify the layout's pinned revision and total file length. For CRISM, acquire a consistent revision before persistent reuse in Release 2. Treat a full-body `200` or mismatched range as a failed partial read and close the response. Preserve the injected fetch interface and existing limits so tests and callers can use it.
- In `backend/app/analyzer/orchestration/service.py`, use the existing `completed` job write as the publication boundary. Write and verify the required result and referenced artifacts before persisting `completed`. Only then publish the in-memory completed state. Keep the final transition coordinated with cancellation and use unique temporary files. Clean up known staging artifacts after failure or restart. Interrupted jobs retain the existing retry behavior.
- On recovery and reuse, evict broken completed entries from the **deduplication lookup**. Keep their historical IDs and use the existing artifact-unavailable responses for reads. Resubmission creates a new job and regenerates what it needs. Validate UUID, manifest and required files, including any science asset declared by the result. Use existing checksum validation, with the warm fast path below after a verified load. Under the service lock, recheck the candidate before replacing its key mapping so concurrent callers share the new job.
- Include the ROI name in the submission key. Use a new key namespace if needed for old job keys. Existing job IDs and their stored artifacts remain readable.

**Acceptance.** Mock a wrong same-length range, wrong revision, truncated body and upstream `200`. Each fails without publishing bytes. Delete or corrupt a job's terrain file and resubmit before and after restart. The old ID reports unavailable and concurrent submissions converge on one replacement job. Simulate interruption before completion and cancellation during final publication. Verify that readers see either a complete result or the appropriate job/error state.

### PR 2 — Add a verified terrain RAM cache and conditional PNG responses

- Put a byte-bounded LRU behind `AnalysisService.load_terrain()` so map, routing and other consumers share it. Cache the verified manifest and arrays returned by `load_terrain_bundle()`; mark shared arrays read-only and audit callers before enabling it. Use analysis ID and artifact revision as identity. Check that the expected files still exist and match the verified generation's file identity or stat signature on a warm read. A changed signature forces disk verification. Coalesce cold loads of the same entry without holding the global job lock during hashing or decompression.
- Use **64 MiB** as the starting per-process budget, configurable down to zero to bypass RAM reuse. Count array `nbytes`, evict least-recently-used entries until the candidate fits, and serve oversized entries from disk without retaining them. Account for in-flight loads and measure peak process RSS separately from resident cache bytes.
- In `backend/app/api/routes/analyses.py`, add conditional handling to the existing PNG GET endpoints. After normal availability checks, derive a validator from the verified revision, display recipe and exact variant parameters. Return bodyless `304` for a matching `If-None-Match` before rendering. A weak validator is suitable for recipe-derived equivalence. Use a strong tag when hashing the actual encoded bytes. Keep analysis PNGs private and add explicit no-store behavior for live job polling. Keep the existing create and cancel endpoints on their current job flow.
- Add structured timings for terrain verification/load, map-package construction, PNG rendering, and route preparation/search. Expose hit, miss, repair and eviction counts through existing logging. Cache a rendered representation only if those timings justify it.

**Acceptance.** Cache-on and cache-off fixtures yield equivalent terrain and route outputs. A warm read skips rehashing and decompression for the same generation. Test oversize bypass, concurrent first read, mutation protection, invalidation and byte-limit eviction. A matching conditional GET skips rendering, and different slope thresholds or display recipes get distinct validators when they affect the output.

## Release 2 — Persistent reuse and mission retention

### PR 3 — Reuse MOLA source windows

Add a small acquisition adapter under `backend/app/data_services/downloads/` and storage logic under `backend/app/data_services/cache/`. Inject the fetcher through `AnalyzerDeps.fetch_range`. Start by storing exact validated ranges, then compare with row-local source-aligned blocks on a repeat-and-pan trace. Use the simplest layout that cuts upstream requests without excessive read amplification. Preserve the existing native stride, exact window assembly and halo. Run the release with direct fetching as a configurable fallback.

Use per-key synchronization around a miss and recheck after taking the lock. Publish verified bytes by writing to a unique temporary file on the same volume, validating them, and atomically renaming. Never use a request-provided URL or filesystem path as the storage path. Apply the same verified contract before adding CRISM byte reuse. Catalog caching can follow as a separate adapter keyed by collection, filters, coverage and pagination. Track catalog freshness separately from source bytes.

**Acceptance.** Compare direct and cached windows including pixels across block boundaries, nodata, the halo and seam-adjacent AOIs. Same-version repeats avoid repeat upstream reads. Different revisions miss. A failed write leaves no reusable artifact. Log bytes fetched, number of requests and latency for each candidate layout.

### PR 4 — Publish versioned derived artifacts and protect mission references

Implement the minimum PostgreSQL migration needed for persistent metadata and mission references in the repository's existing `db` and `migrations` areas. Keep raster bytes in the configured `data_root`. Persist internal relative paths, checksums, size, source revision, last access, freshness and generation state. Begin with reusable terrain across missions. Keep science on its existing pipeline until its source snapshot and degraded outcomes are modeled.

Write immutable generation directories. Commit the ready metadata and mission reference only after files are verified and durable. An interrupted write can leave an orphan directory, which reconciliation may remove after checking for live writers or references. A ready row with a broken file is unavailable and repairable; a refresh produces a new generation and adoption updates the mission reference explicitly. Test the migration against an existing data volume and retain legacy job-folder reads.

Set configurable disk limits for raw and regenerable derived data. Eviction considers complete, unreferenced generations only. In the single-owner release, guard eviction and reader/writer acquisition with the same ownership mechanism. If live references fill the budget, report storage pressure and skip optional cache writes. For production multi-process operation, first add shared ownership and recovery coordination. Per-process locks cannot coordinate separate workers.

**Acceptance.** Fault-inject failure before the database commit and missing files after it. Verify deterministic recovery, checksum rejection, preservation of pinned/active generations during refresh and eviction, and reuse by distinct mission IDs without cross-mission response metadata.

## Release 3 — Prepared offline missions

Implement the typed offline-package endpoints before promising offline mission operation. Record the mission's chosen analysis generation, required asset identities and checksums, package status and missing dependencies. A completed package supports only the features whose dependencies were verified. Store route state durably before advertising restart-safe guidance or replanning; the current `backend/app/routing/api_service.py` holds that state in RAM. Surface unavailable upstream checks as `unable_to_verify` and retain provenance and age for any validated snapshot. A CRISM outage must not become a durable claim of no candidates.

Keep the local backend available for offline routing. Cache the versioned app shell and optional public imagery in the browser. Bound tile RAM in the existing `BaseImagery.ts` path and reuse its coarse-first behavior. If persistent tile caching is needed, prefetch the 42 coarse tiles as recoverable work and report partial coverage when any fetch fails. Browser origin storage is best-effort, so coordinate Cache Storage and IndexedDB budgets and test eviction. Consider binary DEM only after profiling current compressed JSON. Any binary contract must preserve dimensions, affine/projection, sample registration, units, datum and invalid-cell semantics.

**Acceptance.** With outbound access disabled, reload the browser and restart the local API. Open the prepared mission and verify every advertised function. Remove a required artifact or evict browser storage and verify truthful package and map status. Run the same test for a mission that was never prepared.

## Verification and rollout

Run from the repository root in the same Python and Node versions used by CI.

```bash
(cd backend && python -m pip install -e '.[dev]')
(cd backend && python -m pytest)
(cd backend && python scripts/benchmark_analyzer.py)
(cd frontend && npm ci)
(cd frontend && npm test && npm run build)
```

For browser-facing changes, install the Playwright browser for the project (for Chromium, run `npx playwright install chromium` from `frontend/`) and run `npm run test:ui` once the browser acceptance test is in place. Keep normal CI independent of NASA/USGS. Use the existing `python scripts/benchmark_analyzer.py --real` as an opt-in live check with upstream access. For comparisons, keep hardware, fixture set, concurrency, and warm-up consistent.

| Scenario | Evidence to record |
|---|---|
| Cold analysis, same-area repeat and adjacent AOI | End-to-end p50/p95, verified output equivalence, upstream requests/bytes and source cache hits. |
| Repeated map, layer and route reads against one analysis | Terrain load and map/render/search timings separately, conditional GET render count, warm vs. cold p50/p95, cache bytes and peak RSS. |
| Interrupted job, restart, corrupt asset and pinned mission under disk pressure | Rebuild outcome, usable asset count, no lost pinned references, and accurate status messages. |
| Prepared offline mission | Fresh local API and browser reload with upstream blocked, feature-by-feature availability and missing dependencies. |

The earlier offline synthetic run measured roughly 10 ms for verified terrain reload and 220 ms for map-package construction at about 100,000 cells. At 1 million cells the same stages were roughly 60 ms and 530 ms. Use those figures as a starting observation. Set performance targets after measuring the release candidate on the intended machine. Ship an optimization when it improves the corresponding repeated operation without breaking output equivalence or exceeding its memory/storage budget.

Roll out Release 1 with existing fixture data and the RAM cache limit configurable to zero. Keep direct source fetching available when enabling Release 2. Use a staged sample mission to verify each optional layer before expanding use.
