# Coordinate conventions (normative)

MarsNav canonical geographic coordinates are **planetocentric latitude** in decimal degrees and **east-positive longitude** normalized to `[-180, 180)`. The transport object is `{latitude_deg, longitude_deg_east}`. Every incoming source coordinate must retain its original latitude type, longitude direction/range, datum/body/radii and projection metadata, and be transformed at ingestion; no source is assumed canonical.

AOI is an axis-aligned canonical `BoundingBox {west_deg_east, south_deg, east_deg_east, north_deg}`. It may not cross the antimeridian; split it into two AOIs before a request. Bounds use west < east, south < north. Map display labels may use `0–360°E`, but only by conversion at display/export boundaries.

For local grid/routing work, analyzer writes an explicit local projected CRS/WKT plus affine transform, pixel size, origin and north-up flag into layer metadata. Coordinates are metres, x increases east and y increases north in logical grid space; raster row direction is separately recorded and transformed before routing. Compute route distance/heading in that local projection, not in degrees. Elevation is metres relative to the source's declared datum/areoid; never merge vertical datum values without documented reconciliation.

Bearing is degrees clockwise from local/grid north, normalized `[0,360)`. Navigation relative turn is signed `[-180,180)` (positive = right/clockwise). Slope is degrees, roughness records its formula/window/units, duration is minutes, and all API distance fields end `_m`.

The selected Mars ellipsoid/body parameters are an analysis artifact, not implicit EPSG defaults. API validation bounds coordinate values, but adapters must validate source CRS/datum before processing.
