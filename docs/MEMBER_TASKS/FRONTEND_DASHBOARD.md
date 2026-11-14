# Frontend Developer 1 — dashboard, planning UI, assistant, HUD

## Owns

`frontend/src/app`, `components`, `features/dashboard`, `mission`, `routing`, `science`, `ai-assistant`, `marswalk`, and dashboard tests. Do not build Leaflet/Three map rendering, API algorithms, or mutate map-owned component files.

## Required implementation

Create application shell/space for map. Implement mission setup (AOI summary, objective, base/destination), analysis status timeline, source/coverage/freshness panels, route presets, editable soft weights/hard constraints, restore defaults, generate/replan controls, route metrics/elevation/hazard/feasibility/no-route panels, target evidence cards, assistant chat with tool/provenance outputs, and simulated navigation HUD (heading/current point/next waypoint/relative arrow/distance/notifications). Keep advanced data collapsible and explicitly label prototype assumptions.

Use typed API client and Zustand events from `FRONTEND_INTEGRATION.md`; fixtures let all panels work before API completion. Target/route/AOI selection must synchronize via store, never direct map imports. Disable/annotate controls during jobs and render partial/unavailable results honestly.

## Completion

Vitest tests cover form-to-request shape, preset/default restoration, progress, no-route, target focus, assistant failure, and HUD update. Include responsive screenshot evidence. PR contains no changes to `features/mars-map` except agreed interface props/store types.
