# Backend Developer 1 — terrain, routing, replanning, navigation

## Owns

`backend/app/routing/{terrain,costs,pathfinding,feasibility,navigation}`, route/navigation API routes, related schemas only through approved contract PRs, and routing tests. Do not download datasets, generate scientific targets, run LLMs, or create a new app/database configuration.

## Required implementation

Consume canonical regional grid/layer references. Validate projection/valid masks; derive documented slope/roughness only where input supports it; create traversability/hazard explanations. Implement deterministic A* with non-negative valid cost/heuristic, configurable normalized preferences, all hard limits, named presets/default restore constants, metrics/elevation profile, target stops where feasible, return-base accounting/reserve, no-route conflict diagnosis, blocked-region replan, and navigation bearing/relative-turn/waypoint instructions. Record formula/version and source layer IDs in outcomes.

Numerical defaults remain prototype assumptions. No low-resolution DEM may imply rock detection. Unknown terrain must remain an explicit hazardous/excluded configurable condition, never a silent safe zero.

## Completion

Use analyzer-shaped synthetic regional fixtures so work starts independently. Tests prove continuity, deterministic repeat, constraints, blocked avoidance, changed preference behavior, impossible route, metric units, return feasibility and heading guidance. Expose only contract-compliant `RouteResult`/navigation JSON and document any necessary grid contract additions before merging.
