# MarsNav functional specification

## Purpose and scope

MarsNav turns NASA/USGS planetary data into an actionable local Marswalk plan: select an area, state a supported science objective, analyze actual available data, configure safety/mission constraints, produce an explainable deterministic route, and view it in synchronized 2D/3D/dashboard/HUD interfaces. It is a hackathon prototype, not certified astronaut-navigation or life-support software.

The core demonstration is one or two well-supported regions, using at least elevation, imagery, and a third genuinely distinct data category where available. General AOI processing is the design goal; global high-resolution coverage is not claimed.

## Primary journey

1. Explore the global Mars map; choose base, destination, and AOI.
2. Select one supported science objective manually or through the local assistant.
3. Start analysis. The UI reports discovery, selection, acquisition, preprocessing, harmonization, terrain and science stages.
4. Inspect coverage, provenance, missing layers, quality limits, hazards, and evidence-backed targets.
5. Pick a preset or adjust explicit soft weights and hard constraints; generate a route.
6. Compare route metrics, warnings, science value, and return feasibility; see the same route in 2D and DEM-derived 3D.
7. Mark a blocked area to request a constraint-preserving replan.
8. Run simulated navigation using position/heading input and waypoint-relative guidance.

## Inputs and outputs

Inputs are AOI bounds/radius, start/destination, objective category, preferences, constraints, required targets, blocked areas, and an optional natural-language request. Outputs are analysis job progress, source metadata and coverage, processed-layer references, target/evidence records, an explicit feasible/no-route result, navigation guidance, and assistant responses grounded in tools/RAG.

## Behaviour and truthful failure handling

Only data that is discovered, accessible, processed, valid, and spatially overlapping may appear as evidence/layers. Missing or unsupported products yield explicit unavailable/partial states, not invented values. Unknown terrain is never treated as safe. A no-route response contains conflicts and no unsafe fallback geometry. The assistant reports tool failures and never creates science coordinates or route measurements itself.

## Supported prototype capabilities

- Global lower-resolution basemap plus local processed imagery/elevation overlays.
- Configurable A* routing over an analyzer-produced grid with slope, roughness, hazards, data confidence, science value, blocked cells and hard limits.
- Grounded targets for a small supported objective set (initially hydrated-mineral evidence, mapped geological feature, and named/local target where records exist).
- Local API/UI/database/cache and optional local Ollama/RAG after data and model preparation.

## Non-goals

No planet-wide high-resolution browser raster, real suit localization, autonomous vehicle control, real-time weather/radiation routing, universal PDS format support, research-grade calibration written from scratch, or NASA-certified thresholds. Defaults are labeled prototype assumptions. Raw model/data acquisition and the actual solution implementation are reserved for the event in accordance with competition rules.

## Demo priority

Make automatic local data analysis + truthful coverage + deterministic configurable routing work first. Then map/dashboard synchronization, replanning, local AI tool orchestration, 3D and HUD. See `DEMO_PLAN.md`.
