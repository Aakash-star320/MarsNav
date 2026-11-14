import type { ProcessedLayer } from "../../types/contracts";
export type Projection = {
  kind: "mars-local-equirectangular";
  radius_m: number;
  latitude_origin_deg: number;
  longitude_origin_deg_east: number;
};
/** Proposed processed DEM adapter contract. Affine maps sample column,row to local metres. */
export type Dem = {
  version: 1;
  synthetic: boolean;
  width: number;
  height: number;
  bounds: ProcessedLayer["bounds"];
  projection: Projection;
  affine: [number, number, number, number, number, number];
  sample_registration: "point";
  vertical_datum: string;
  units: "m";
  values: (number | null)[];
};
/** Display adapter metadata, deliberately separate from canonical transport layers. */
export type MapLayer = {
  layer: ProcessedLayer;
  projection: "MARS:CANONICAL_ANGULAR";
  format: "image";
  source: string;
  synthetic: boolean;
  coverage: "available" | "partial" | "unavailable" | "unknown";
  legend: string;
  colors: string[];
};
export type Mode = "inspect" | "base" | "destination" | "aoi" | "blocked";
