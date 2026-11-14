# Database schema and migrations

PostgreSQL stores relational state and JSON metadata, not raster/model blobs. Files live under `data/{raw,processed,derived}` using content-addressed or versioned relative paths.

| Table | Essential columns |
|---|---|
| `missions` | id, name, objective, roi_json, base_json, destination_json, active_analysis_id, created_at |
| `analysis_jobs` | id, mission_id FK, stage, progress, message, warnings_json, error_code, timestamps |
| `datasets` | id, source, product_id, version, instrument, category, metadata_json, footprint_json, coverage_json, provenance_url |
| `dataset_assets` | id, dataset_id FK, kind, relative_path, checksum, processing_state, created_at |
| `cache_entries` | key, dataset_id FK, local_asset_id, downloaded_at, last_checked_at, freshness, etag/version |
| `regional_analyses` | id, mission_id FK, roi_json, projection_wkt, state, result_json, created_at |
| `processed_layers` | id, analysis_id FK, dataset_asset_id FK, kind, relative_path, metadata_json |
| `science_targets` / `science_evidence` | ids, analysis/target FK, location/evidence/provenance/limits |
| `route_requests` / `routes` | input JSON/version, geometry JSON, metrics JSON, feasibility, conflicts, analysis FK |
| `blocked_areas` | id, mission_id FK, bounds_json, reason, created_at |
| `rag_documents` | id, source URI, content hash, local path, indexed_at; vectors in sqlite-vec local index |

Initial Alembic revision creates tables, FK indexes and unique `(source, product_id, version)` dataset identity. Subsequent migrations are forward-only and include backfill/rollback notes. Store source metadata verbatim enough to reproduce selection; checksum every downloaded/derived asset. Retain active asset versions until no mission references them.
