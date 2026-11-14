# Frontend Developer 2 — 2D/3D Mars map

## Owns

`frontend/src/features/mars-map`, map-specific hooks/utils/components/tests. Do not own dashboard layout/forms, science scoring, route calculations, or backend calls beyond typed shared API/store adapters.

## Required implementation

Build a Leaflet Mars 2D component with explicit Mars CRS/coordinate display; coordinate/base/destination/AOI interactions; imagery, elevation, slope/roughness/hazard/science/coverage overlays; independent visibility/opacity controls; source and missing-coverage indication; target, base, destination, route, alternative, waypoint and astronaut markers. Draw blocked areas and emit typed `BlockedArea` to store; do not compute replan locally.

Build a local DEM-derived Three/R3F terrain view receiving processed elevation metadata/data and same canonical route/target geometry. Provide camera/rotate/zoom and make 2D/3D share mission selection. Use layer bounds/affine/projection metadata, validate inputs, and surface unsupported 3D/missing DEM clearly.

## Completion

Component tests verify store events, overlay visibility, target/route synchronization, coordinate conversion, unavailable display and blocked-area action. Story/mock cases use only `data/sample` synthetic assets. PR includes screenshots and does not edit dashboard feature modules.
