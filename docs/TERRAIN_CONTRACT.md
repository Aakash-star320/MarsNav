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
