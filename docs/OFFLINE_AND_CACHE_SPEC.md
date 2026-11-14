# Offline and cache specification

`data/raw`, `data/processed`, and `data/derived` hold versioned source/derived assets outside Git. PostgreSQL maps product identity and checksums to local paths; it never stores large raster blobs. Cache lookup is by source/product/version/checksum, then validates file existence/checksum before reuse.

Lifecycle: discovered → selected → downloading → downloaded → validating → processing → ready/failed. Freshness states are `up_to_date`, `update_available`, `unable_to_verify`, `downloading`, `processing`, `ready`, `failed`. A manual refresh checks remote metadata only when online and creates a new asset version. It never overwrites an active mission analysis; user explicitly adopts a newer analysis.

Offline mode disables discovery, remote checks and new downloads with an actionable `unable_to_verify` response. It retains local UI/API/database, cached data, processed layers, routes, routing and prepared AI/RAG. Storage pressure is reported; eviction must not delete assets referenced by active/pinned missions. Cache API returns paths only via controlled layer-serving endpoints, never arbitrary filesystem access.
