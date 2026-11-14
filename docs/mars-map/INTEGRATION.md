# Integration handoff

## Ownership and mounting

The separate map-preview.html page is a frontend harness around your map module. The left rail is **map-specific controls and demo controls**, not an implementation of your teammate's dashboard feature. Replace the harness when embedding in the actual shell.

```tsx
import { MarsMap } from './features/mars-map/MarsMap';
import { useMissionStore } from './store/missionStore';

<MarsMap onBlockedArea={(area) => {
  // Central shared API adapter sends this area with mission/analysis/version IDs.
  // On response:
  // useMissionStore.getState().setActiveRoute(response);
  // useMissionStore.setState({replan: response.feasible ? 'ready' : 'failed'});
  // On request failure: preserve pending/stale route and expose the API error.
}} />
```

Do not mount `Demo` in the team dashboard: it resets state and loads fixtures. `MarsMap` does not fetch backend data or calculate routes. Omit `demoControls` for a non-demo mount. Both views consume the same store. UI view changes preserve mission selection; unfinished draws are cancelled when switching views.

## Shared changes to coordinate with Aakash/dashboard owner

Preserve their new work when merging; do not replace their whole `missionStore.ts` blindly. New fields: base, destination, AOI, processed display layers/settings/status, DEM, alternatives, blocked areas, navigation, active view, drawing draft, replan state. Existing selectedPoint/selectedTarget/activeRoute/targets actions remain.

`setAoi` clears all prior region-derived data. `setBase` and `setDestination` clear routes and navigation. Pending blocked edits retain the old route as an explicitly stale amber reference. Removing a block also requests a replan. A production route adapter must guard analysis/request versions so late responses cannot overwrite the current mission; this demo has no asynchronous backend.

## Transport versus display adapters

The original `ProcessedLayer` transport shape is retained. A separate `MapLayer` wrapper contains display-only metadata: source label, explicit image projection/format, coverage status, synthetic label, legend and colors. `setLayers` takes these wrappers. The existing seven `kind` values are used without parallel science models.

MapLayer supports `format: 'image'` and `projection: 'MARS:CANONICAL_ANGULAR'`. Images must be processed by the backend into that display projection, have valid geographic bounds, and preserve no-data transparency. Coverage percentage is layer validity, not automatically AOI coverage. Dataset IDs are retained on the canonical layer. The adapter must resolve actual provenance text from backend dataset records; do not label real data synthetic or substitute local fixtures for missing products.

## Proposed DEM adapter (not an existing API promise)

`types.ts` defines `Dem`:

- `version: 1`, `units: 'm'`, explicit `vertical_datum`.
- `width`, `height`, point samples in row-major `values`; null means no data.
- `sample_registration: 'point'`.
- `affine: [x0, dx_col, dx_row, y0, dy_col, dy_row]` maps sample indices to local metres.
- Local x east and y north. Negative y row step is valid and used in fixture.
- Projection `mars-local-equirectangular` supplies sphere radius, origin latitude and longitude.
- Geographic bounds describe the projected grid extent.

Forward projection: `x = R cos(lat0) (lon-lon0)`, `y = R (lat-lat0)` with angles in radians. This is an explicit supported local spherical display adapter, not universal geodesy. It must not be applied to arbitrary WKT or an ellipsoidal DEM. Existing regional `projection_wkt` alone is insufficient; the backend must export a compatible processed adapter payload, or this renderer needs an additional verified projection implementation.

Terrain meshes use sample elevations directly. A cell with any missing corner is omitted. Surface attachments use bilinear sampling only when all four samples are valid. 3D route/target data uses the same canonical geographic coordinates as 2D. Height exaggeration scales terrain and attachments together and is labelled.

## Backend still owns

- Discovery/download/provenance, scientific processing, slope/roughness/hazard/science analysis.
- Approved processed layer and DEM contracts, coordinate transformation and no-data masks.
- Analysis jobs, mission persistence, request versioning and validation.
- Route generation, alternative routes, replanning, feasibility, navigation guidance.

The existing shared contracts (including `BlockedArea` and `NavigationState`) are preserved byte-for-byte; this package adds no endpoint. An eventual new backend DEM contract should follow your schema/OpenAPI/TS approval workflow.

## Integration sequence

1. Review and merge shared store/types with the dashboard owner.
2. Copy map feature and relevant dependencies/configuration; preserve unrelated dashboard code.
3. Agree/version the proposed DEM and raster display adapter contracts.
4. Mount `MarsMap` in the shared shell, without `Demo`.
5. Feed completed analysis assets and targets through centralized adapters.
6. Wire blocked-area callback to the replan API and surface loading/errors.
7. Feed route alternatives and simulated/real input navigation state.
8. Verify real product CRS, datum, affine alignment, coverage and source labels.
9. Capture screenshots and run component/browser tests against real processed fixtures before claiming real-data completion.

## Latest contract compatibility

Adapted to MarsNav-main (2).zip. Processed-layer fixtures include required availability and limitations. Serialized route fixtures and failure responses include segments, elevation_profile, alternatives and conflict_details collections. These collections are empty when the synthetic demo provides no such result; no elevation profile is fabricated. The demo keeps full prerecorded route candidates in its display store. A real adapter must map RouteResult.alternatives (RouteAlternative[]) to display candidates rather than assume they are full RouteResult objects.

The DEM payload remains an explicit local display adapter, not a replacement for LocalGridMetadata. Real integration must verify layer.grid, CRS/WKT, affine registration and vertical datum before constructing it; arbitrary WKT is not supported. Synthetic fixture string IDs are local demo identifiers, not backend UUID request payloads.
