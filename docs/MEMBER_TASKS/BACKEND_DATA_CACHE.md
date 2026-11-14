# Backend Developer 2 — acquisition, storage/cache, metadata, freshness, support, presentation

## Owns

`backend/app/data_services/{downloads,cache,metadata,freshness}`, `db`, `migrations`, mission/data APIs, cache tests, plus demo capture/edit/submission assets. Do not implement PDS/ODE discovery semantics, preprocessing/science logic, or routing internals.

## Required implementation

Implement selected-product download interface with resumable/checked acquisition where source permits; deterministic relative asset paths, checksums, metadata/provenance persistence, cache reuse, lifecycle/freshness states, manual refresh, and active-version protection. Implement lightweight mission persistence and database migrations/models consistent with `DATABASE_SCHEMA.md`. Provide service adapters for analyzer and read APIs for UI. Offline requests must keep cached assets usable and return truthful inability to refresh.

Use filesystem for large files, PostgreSQL only for records. Validate size/checksum/content type and never accept arbitrary URL/path traversal. Keep workload intentionally bounded; presentation work includes recording the approved demo flow, narration, screenshots and submission asset checklist.

## Completion

Tests cover duplicate cache prevention, corrupt/missing asset, failed download, freshness states, active data non-overwrite, offline behavior and migration upgrade. PR includes migration notes and a demo asset handoff checklist; raw NASA data and rendered video exports stay out of Git unless explicitly small/licensed.
