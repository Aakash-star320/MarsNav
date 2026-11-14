# Test plan and acceptance gates

Use synthetic fixtures for unit/component boundaries, clearly labelled; final demo claims require separate recorded tests against actual source products.

| Area | Required assertions | Owner |
|---|---|---|
| Coordinates | longitude normalization, source conversion, AOI antimeridian rejection, local-grid affine roundtrip | Aakash/Routing |
| Connectors/analyzer | valid AOI discovery, overlap rejection, unavailable status, selection/provenance, masks/aligned outputs | Aakash |
| Cache | checksum reuse, freshness transitions, active-version preservation, offline refusal | Data/cache |
| Routing | connected path, max-slope/blocked avoidance, deterministic output, weights affect output, no-route conflicts, return limit/replan | Routing |
| AI | schema extraction, actual tool call, tool error reporting, retrieval citation, offline prepared mode | Aakash |
| UI | AOI triggers job, map/dashboard synchronization, typed mock responses, honest missing layers, route/replan/HUD rendering | Frontend |
| Integration | OpenAPI/type compatibility, one API app, smoke flow against fixtures | Aakash |

CI blocks merge on backend import/contract tests and frontend lint/type/test. Add processing integration tests marked `real_data` and do not run them by default. Acceptance means all core demo flow states work—including partial data/no-route—not merely a successful happy path.
