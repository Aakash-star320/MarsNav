# Terrain artifact contract (analyzer → routing, map, 3D)

The analyzer publishes one aligned terrain bundle per analysis. Large arrays live in a single compressed `.npz` file; JSON carries only references, metadata and checksums. Routing may re-derive slope and roughness from `elevation_m` and `valid` (see `ROUTING_SPEC.md`); the analyzer's copies are provided for display and as a reference, and record the algorithm used.

## Files

`<analysis_id>/terrain.npz` and `<analysis_id>/terrain.manifest.json`. Both are written atomically (temporary file, then rename); the manifest is written last, so a manifest that exists always points at a complete array file.

## Arrays (all shape `(rows, cols)`, identical grid)

| Array | dtype | Meaning |
|---|---|---|
| `elevation_m` | float32 | Elevation in metres; `NaN` where invalid |
| `slope_deg` | float32 | Slope magnitude in degrees from real cell spacing; `NaN` where undefined |
| `roughness_m` | float32 | Standard deviation of elevation in a 3×3 window (metres); `NaN` where too few valid cells |
| `valid` | bool | True where the source elevation is valid. Invalid is never the same as zero |
| `source_id` | uint8 | Index into `manifest.sources`; `255` = no source |
| `quality_flags` | uint8 | Bit 0: native resolution coarser than 100 m. Bit 1: interpolated source product. Bit 2: slope undefined here. Bit 3: roughness undefined here |

Row 0 is the northern edge and columns increase east (`north_up = true`, `raster_rows_increase_south = true`). Grid space: x increases east, y increases north, in metres. Elevations are never filled or imputed.

## Grid

`manifest.grid` is a `LocalGridMetadata`. Cell centre of `(row, col)` is
`x = affine[2] + affine[0]·(col + 0.5)`, `y = affine[5] + affine[4]·(row + 0.5)`, with `affine = [pixel_size_x_m, 0, origin_x_m, 0, -pixel_size_y_m, origin_y_m]` (`origin` is the north-west corner). The local CRS is an equirectangular projection with the standard parallel at the window's centre latitude on the source sphere, so source longitude/latitude grids map to this metric grid without resampling. `pixel_size_x_m = R·cos(φ0)·Δλ` and `pixel_size_y_m = R·Δφ`.

## Layers

Each array is exposed as a `ProcessedLayer` (`kind` = `elevation`, `slope`, `roughness`, `validity`, `source`). `uri` is `<relative npz path>#<array name>`. `resolution_m_per_px` is the **native source resolution**, not the grid spacing. `limitations` and `provenance.output_checksum_sha256` (checksum of the `.npz`) are always set.

## Rules for consumers

- Check `valid` before reading `elevation_m`; treat `NaN` as unknown, not zero or flat.
- Never read coarse-source cells as evidence of astronaut-scale safety; `quality_flags` bit 0 marks them.
- Verify the checksum before use; reject a bundle whose array shapes disagree with `manifest.shape`.

## Map display package (analyzer → 2D/3D map)

`GET /api/v1/analyses/{id}/map` returns a `MapPackage` (`app/schemas/map_display.py`, mirrored by `frontend/src/features/mars-map/types.ts`): `layers` (`MapLayerEntry`: a `ProcessedLayer` plus display metadata) and `dem` (`DemPayload`). `GET /api/v1/analyses/{id}/layers/{elevation|slope|roughness}.png` serves each layer image.

- Images are plate-carrée RGBA PNGs in the canonical angular display projection (`MARS:CANONICAL_ANGULAR`). Invalid cells are fully transparent, never coloured as zero. The terrain grid is already regular in longitude and latitude, so no resampling happens.
- `dem.bounds` is the extent of the **sample points** (cell centres, point registration). Every layer's `bounds` equals `dem.bounds` exactly, because the 3D view rejects overlays whose bounds differ. Images are therefore draped over a footprint half a source cell smaller than the cell edges.
- The DEM affine is `[x0, dx_col, dx_row, y0, dy_col, dy_row]` in local metres about the grid centre on the 3,396,190 m source sphere (`x = R cos(lat0)(lon - lon0)`, `y = R (lat - lat0)`); `dy_row` is negative because rows run north to south.
- Grids larger than 257 cells on a side are decimated by an integer stride for display only (`style_hint.stride` and a note say so). Analysis keeps the full-resolution bundle.
- Colour scales: slope uses a fixed 0-35 degree scale; elevation and roughness use the 2nd to 98th percentile of valid cells. The legend text states the actual range and the data source.
- `vertical_datum` is reported as not stated, because the source file header does not state it.

## Routing access

In the same app, routing loads terrain with `load_routing_terrain(service, analysis_id, analysis_version)` (`app/analyzer/integration/routing_terrain.py`), where `service` is `app.api.routes.analyses.get_service()`. It returns a frozen `RoutingTerrain` with the six arrays, `grid`, `bounds`, `sources`, `limitations`, `sha256`, `analysis_version` and `terrain_version`, and these helpers:

- `lonlat_to_cell(LonLat) -> (row, col) | None` (None outside the grid), `cell_center_lonlat(row, col)`, `cell_center_xy(row, col)`.
- `lonlat_to_xy(LonLat)` and `xy_to_lonlat(x, y)` for the local metric frame (x east, y north, origin at the centre of `bounds`).
- `is_usable(row, col)`, which is the `valid` mask.

Failures raise `TerrainAccessError` with `code` = `not_found`, `not_ready`, `version_mismatch` (the `RouteRequest.analysis_version` differs from the analysis's) or `unavailable` (artifact missing or failed checksum). The arrays are verified (checksum, dtypes, shapes, mask consistency) before they are returned.

Outside the app, `GET /api/v1/analyses/{id}/terrain.npz?analysis_version=...` returns the same `.npz` with headers `X-Terrain-Sha256`, `X-Analysis-Version` and `X-Terrain-Version`; errors use 404 (`not_found`, `unavailable`) and 409 (`not_ready`, `version_mismatch`) with `{error_code, message}`.
