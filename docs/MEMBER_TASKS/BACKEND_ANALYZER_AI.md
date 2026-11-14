# Aakash — analyzer, science intelligence, local AI/RAG, integration

## Owns

`backend/app/connectors/{ode,pds,common}`, `analyzer/**`, `ai/**`, analysis/assistant API routes, integration fixtures/tests, and end-to-end contract review. Do not implement pathfinding/terrain cost internals or cache/downloader persistence.

## Build order and deliverables

1. Implement connector interfaces with recorded official source samples; normalize source metadata, footprint/coordinate semantics, download references and errors. Do not claim endpoint/product support before test validation.
2. Build AOI expansion, candidate overlap/relevance selection, stageful analysis jobs, partial-result warnings, and acquisition interface calls.
3. Implement documented product-family preprocessing orchestration, validation, masking, local-grid alignment and provenance. Return layer references, never raw data in API JSON.
4. Implement supported target objectives using real georeferenced records/layers. Each target needs evidence, measured-vs-heuristic flag, source URI and confidence/limits.
5. Integrate Ollama adapter, local sqlite-vec RAG and strictly typed tool registry. Assistant tools call the real service adapters or mocks behind the same interface.
6. Own final OpenAPI/UI/backend fixture integration and resolve contract mismatches.

## Inputs/outputs and constraints

Consume `RegionOfInterest`, mission objective and data-service acquisition contract. Produce `AnalysisJob`, `RegionalAnalysisResult`, `ProcessedLayer`, `ScienceTarget`, and `AssistantResponse` per shared models. Honor preprocessing and coordinate policies, preserve missing coverage, and route no fabricated science outputs. Use Python/FastAPI/Pydantic/httpx/Rasterio/pyproj; ISIS only for a documented family.

## Tests / done / PR

Tests cover overlap filtering, bad/unsupported metadata, NoData propagation, grid agreement, partial result, evidence grounding, tool error and retrieval citation. Done when routing can consume fixture or analyzer regional representation and UI can complete analysis flow with no implementation dependency on teammates. PRs include source proof/sample fixture, contract changes, and end-to-end smoke evidence.
