"""Write and verify the aligned terrain bundle described in ``docs/TERRAIN_CONTRACT.md``."""
from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

import numpy as np
from pydantic import BaseModel, Field

from app.connectors.usgs.mola import MolaWindow
from app.schemas import BoundingBox, DatasetRecord, LocalGridMetadata, ProcessedLayer, ProcessingProvenance

from .terrain import roughness_std, slope_deg

SPHERE_RADIUS_M = 3_396_190.0      # radius stated in the source CRS text
RECIPE_VERSION = "terrain-bundle/1"
NO_SOURCE = 255
FLAG_COARSE, FLAG_INTERPOLATED, FLAG_NO_SLOPE, FLAG_NO_ROUGHNESS = 1, 2, 4, 8
COARSE_THRESHOLD_M = 100.0
ARRAYS = {"elevation_m": "float32", "slope_deg": "float32", "roughness_m": "float32",
          "valid": "bool", "source_id": "uint8", "quality_flags": "uint8"}
KIND = {"elevation_m": "elevation", "slope_deg": "slope", "roughness_m": "roughness", "valid": "validity", "source_id": "source"}
UNITS = {"elevation_m": "m", "slope_deg": "deg", "roughness_m": "m", "valid": "boolean", "source_id": "index"}


class TerrainBundleError(ValueError):
    pass


class TerrainManifest(BaseModel):
    analysis_id: UUID
    terrain_version: str = RECIPE_VERSION
    npz_file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shape: tuple[int, int]
    bounds: BoundingBox
    grid: LocalGridMetadata
    sources: list[dict[str, object]]
    arrays: dict[str, str]
    generated_at: datetime
    limitations: list[str]


class TerrainBundle(BaseModel):
    manifest: TerrainManifest
    layers: list[ProcessedLayer]


def _local_wkt(lat0: float, lon0: float) -> str:
    r = SPHERE_RADIUS_M
    return (
        'PROJCRS["Mars equirectangular local grid",BASEGEOGCRS["GCS_Mars",DATUM["D_Mars",ELLIPSOID["Mars sphere",'
        f'{r:.0f},0,LENGTHUNIT["metre",1]]],PRIMEM["Reference_Meridian",0]],'
        'CONVERSION["Equidistant Cylindrical",METHOD["Equidistant Cylindrical"],'
        f'PARAMETER["Latitude of 1st standard parallel",{lat0:.9f}],PARAMETER["Longitude of natural origin",{lon0:.9f}],'
        'PARAMETER["False easting",0],PARAMETER["False northing",0]],'
        'CS[Cartesian,2],AXIS["easting (X)",east],AXIS["northing (Y)",north],LENGTHUNIT["metre",1]]'
    )


def _grid(bounds: BoundingBox, shape: tuple[int, int]) -> LocalGridMetadata:
    rows, cols = shape
    lat0 = (bounds.north_deg + bounds.south_deg) / 2
    lon0 = (bounds.east_deg_east + bounds.west_deg_east) / 2
    dlam = math.radians((bounds.east_deg_east - bounds.west_deg_east) / cols)
    dphi = math.radians((bounds.north_deg - bounds.south_deg) / rows)
    px, py = SPHERE_RADIUS_M * math.cos(math.radians(lat0)) * dlam, SPHERE_RADIUS_M * dphi
    ox = SPHERE_RADIUS_M * math.cos(math.radians(lat0)) * math.radians(bounds.west_deg_east - lon0)
    oy = SPHERE_RADIUS_M * math.radians(bounds.north_deg - lat0)
    return LocalGridMetadata(
        crs_wkt=_local_wkt(lat0, lon0), affine_transform=[px, 0.0, ox, 0.0, -py, oy], pixel_size_x_m=px, pixel_size_y_m=py,
        origin_x_m=ox, origin_y_m=oy, north_up=True, raster_rows_increase_south=True, body_name="Mars",
        horizontal_datum="D_Mars (sphere)", vertical_datum=None,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, writer) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("wb") as f:
            writer(f)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def build_terrain_bundle(
    window: MolaWindow, dataset: DatasetRecord, analysis_id: UUID, out_dir: Path, halo_px: int = 1,
    generated_at: datetime | None = None,
) -> TerrainBundle:
    """Derive slope/roughness on the halo-padded window, trim the halo, and publish the bundle."""
    z, valid = window.elevation_m, window.valid
    if min(z.shape) <= 2 * halo_px:
        raise TerrainBundleError("window is too small to trim the derivative halo")
    slope, slope_ok = slope_deg(z, valid, window.pixel_size_x_m, window.pixel_size_y_m)
    rough, rough_ok = roughness_std(z, valid)
    trim = (slice(halo_px, z.shape[0] - halo_px), slice(halo_px, z.shape[1] - halo_px))
    z, valid, slope, slope_ok, rough, rough_ok = (a[trim] for a in (z, valid, slope, slope_ok, rough, rough_ok))
    d = (window.bounds.east_deg_east - window.bounds.west_deg_east) / window.elevation_m.shape[1]
    bounds = BoundingBox(
        west_deg_east=window.bounds.west_deg_east + halo_px * d, south_deg=window.bounds.south_deg + halo_px * d,
        east_deg_east=window.bounds.east_deg_east - halo_px * d, north_deg=window.bounds.north_deg - halo_px * d,
    )
    coarse = (dataset.resolution_m_per_px or 0) >= COARSE_THRESHOLD_M
    flags = np.zeros(z.shape, dtype=np.uint8)
    flags[:] |= np.uint8(FLAG_COARSE if coarse else 0) | np.uint8(FLAG_INTERPOLATED if "interpolated" in (dataset.processing_level or "") else 0)
    flags[~slope_ok] |= FLAG_NO_SLOPE
    flags[~rough_ok] |= FLAG_NO_ROUGHNESS
    arrays = {
        "elevation_m": z.astype(np.float32), "slope_deg": slope.astype(np.float32), "roughness_m": rough.astype(np.float32),
        "valid": valid.astype(bool), "source_id": np.where(valid, 0, NO_SOURCE).astype(np.uint8), "quality_flags": flags,
    }
    folder = out_dir / str(analysis_id)
    folder.mkdir(parents=True, exist_ok=True)
    npz_path, manifest_path = folder / "terrain.npz", folder / "terrain.manifest.json"
    _atomic_write(npz_path, lambda f: np.savez_compressed(f, **arrays))
    grid = _grid(bounds, z.shape)
    manifest = TerrainManifest(
        analysis_id=analysis_id, npz_file="terrain.npz", sha256=_sha256(npz_path), shape=z.shape, bounds=bounds, grid=grid,
        sources=[{"index": 0, "dataset_id": str(dataset.id), "product_id": dataset.product_id, "native_resolution_m": dataset.resolution_m_per_px}],
        arrays=dict(ARRAYS), generated_at=generated_at or datetime.now(timezone.utc),
        limitations=[*dataset.limitations, "Derivatives use the source grid spacing; coarse terrain cannot resolve rocks or small obstacles."],
    )
    _atomic_write(manifest_path, lambda f: f.write(manifest.model_dump_json(indent=2).encode("utf-8")))
    provenance = ProcessingProvenance(
        recipe_version=RECIPE_VERSION, parameters={"halo_px": halo_px, "roughness_window": "3x3 std", "slope": "central difference"},
        output_checksum_sha256=manifest.sha256, generated_at=manifest.generated_at,
    )
    layers = [
        ProcessedLayer(
            id=uuid5(analysis_id, name), kind=KIND[name], uri=f"{analysis_id}/terrain.npz#{name}", bounds=bounds,
            resolution_m_per_px=dataset.resolution_m_per_px or grid.pixel_size_y_m,
            valid_percent=100.0 * float((np.isfinite(arrays[name]) if arrays[name].dtype.kind == "f" else arrays["valid"]).mean()), units=UNITS[name], dataset_ids=[dataset.id], grid=grid,
            provenance=provenance, limitations=manifest.limitations,
        )
        for name in KIND
    ]
    return TerrainBundle(manifest=manifest, layers=layers)


def load_terrain_bundle(manifest_path: Path) -> tuple[TerrainManifest, dict[str, np.ndarray]]:
    """Load a bundle and verify checksum, array set, dtypes, shapes and mask consistency."""
    manifest = TerrainManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    npz_path = manifest_path.parent / manifest.npz_file
    if not npz_path.is_file():
        raise TerrainBundleError("array file is missing")
    if _sha256(npz_path) != manifest.sha256:
        raise TerrainBundleError("checksum mismatch: array file is corrupt or was replaced")
    with np.load(npz_path) as data:
        arrays = {k: data[k] for k in data.files}
    if set(arrays) != set(ARRAYS):
        raise TerrainBundleError(f"unexpected array set: {sorted(arrays)}")
    for name, dtype in ARRAYS.items():
        if arrays[name].dtype != np.dtype(dtype) or arrays[name].shape != manifest.shape:
            raise TerrainBundleError(f"{name}: expected {dtype} {manifest.shape}, got {arrays[name].dtype} {arrays[name].shape}")
    if not np.array_equal(np.isfinite(arrays["elevation_m"]), arrays["valid"]):
        raise TerrainBundleError("valid mask disagrees with finite elevations")
    return manifest, arrays
