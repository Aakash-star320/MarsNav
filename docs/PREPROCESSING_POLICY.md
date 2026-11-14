# Preprocessing and validation policy

1. Discover candidate metadata/footprints; reject non-overlapping or unsupported products.
2. Prefer documented, map-projected science-ready assets. For raw products, only execute a documented and tested ISIS/GDAL/Rasterio recipe for that family.
3. Validate checksum/label, source CRS/datum/longitude conventions, raster dimensions/bands, units, NoData and quality fields.
4. Convert to a canonical local projected analysis grid. Clip with the AOI plus routing margin, preserve original resolution where practical, and resample explicitly: continuous elevation uses bilinear/cubic only when justified; masks/categories use nearest neighbour.
5. Persist source asset, recipe version, parameters, grid definition, masks, checksums and derived provenance. Align layers only after checking bounds/affine transforms.

NoData/fill values and documented quality masks propagate to output validity masks. Never globally impute missing cells or remove statistical outliers without documented scientific grounds. Genuine unusual measurements remain. Invalid/unsupported assets become unavailable with a reason. Validate post-processing statistics, valid-coverage percentage, expected extent/units, grid alignment and source-to-output provenance. Routing receives explicit unknown/low-confidence cells and applies the configured policy; it may not silently traverse unknown as safe.
