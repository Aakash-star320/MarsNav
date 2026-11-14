import demText from "../../../../data/sample/dem.synthetic.json?raw";
import missionText from "../../../../data/sample/mission.synthetic.json?raw";
import type { Dem, MapLayer } from "./types";
import type {
  BoundingBox,
  LonLat,
  RouteResult,
  ScienceTarget,
  ProcessedLayer,
} from "../../types/contracts";
import { useMissionStore } from "../../store/missionStore";
import { routeHits } from "./geometry";
export const demoDem = JSON.parse(demText) as Dem;
export const mission: {
  bounds: BoundingBox;
  base: LonLat;
  destination: LonLat;
  route: RouteResult;
  alternatives: RouteResult[];
  targets: ScienceTarget[];
} = JSON.parse(missionText);
const assets = import.meta.glob("../../../../data/sample/*.png", {
  query: "?url",
  import: "default",
  eager: true,
}) as Record<string, string>;
const info: Record<ProcessedLayer["kind"], [string, string[]]> = {
  imagery: ["Synthetic shaded relief", ["#6c3924", "#d2a77c"]],
  elevation: ["Synthetic elevation · metres", ["#305096", "#ed9b37"]],
  slope: ["Synthetic slope · 0–35°", ["#46b9a0", "#fa3c28"]],
  roughness: [
    "Illustrative roughness pattern · unitless",
    ["#5f50a0", "#cd78d7"],
  ],
  hazard: [
    "Illustrative hazard score · not a safety assessment",
    ["#8c6e3c", "#fa1e23"],
  ],
  science: [
    "Illustrative relevance · no measured evidence",
    ["#4b376e", "#9bcdE1"],
  ],
  coverage: ["Teal: fixture samples / red: missing", ["#2a8c85", "#ec6450"]],
  validity: ["Valid-data mask · not shown as an overlay", ["#2a8c85", "#ec6450"]],
  source: ["Source product index · not shown as an overlay", ["#305096", "#ed9b37"]],
};
export const demoLayers: MapLayer[] = (
  Object.keys(info) as ProcessedLayer["kind"][]
).map((kind) => ({
  layer: {
    id: `fixture-${kind}`,
    kind,
    uri: assets[`../../../../data/sample/${kind}.synthetic.png`],
    bounds: mission.bounds,
    resolution_m_per_px: 2400 / 767,
    valid_percent: 97.5694,
    units: kind === "elevation" ? "m" : "synthetic",
    dataset_ids: [],
    style_hint: {},
    availability: "partial",
    limitations: ["Synthetic fixture; not a NASA observation or terrain assessment."],
  },
  projection: "MARS:CANONICAL_ANGULAR",
  format: "image",
  source: "Local deterministic fixture • seed 42",
  synthetic: true,
  coverage: "partial",
  legend: info[kind][0],
  colors: info[kind][1],
}));
export function loadDemo() {
  useMissionStore.getState().reset();
  useMissionStore.setState({
    base: mission.base,
    destination: mission.destination,
    aoi: mission.bounds,
    activeRoute: mission.route,
    alternatives: mission.alternatives,
    targets: mission.targets,
    dem: demoDem,
    layers: demoLayers,
    layerSettings: Object.fromEntries(
      demoLayers.map((l) => [
        l.layer.id,
        {
          visible: l.layer.kind === "imagery",
          opacity: l.layer.kind === "imagery" ? 1 : 0.55,
        },
      ]),
    ),
    focus: Date.now(),
  });
}
/** Only a prerecorded response simulator. Never calculates a safe route. */
export function applyFixtureResponse() {
  const s = useMissionStore.getState();
  const same = (a?: LonLat, b?: LonLat) =>
    a &&
    b &&
    a.latitude_deg === b.latitude_deg &&
    a.longitude_deg_east === b.longitude_deg_east;
  const match =
    s.aoi &&
    JSON.stringify(s.aoi) === JSON.stringify(mission.bounds) &&
    same(s.base, mission.base) &&
    same(s.destination, mission.destination);
  const route = match
    ? [mission.route, ...mission.alternatives].find(
        (r) => !routeHits(r, s.blockedAreas),
      )
    : undefined;
  const result: RouteResult = route
    ? {
        ...route,
        warnings: [
          ...route.warnings,
          "Prerecorded fixture response; no routing calculation performed.",
        ],
      }
    : {
        id: "fixture-no-route",
        feasible: false,
        segments: [],
        elevation_profile: [],
        alternatives: [],
        conflict_details: [],
        geometry: [],
        waypoints: [],
        target_ids: [],
        warnings: ["Synthetic response only"],
        constraint_conflicts: [
          "No prerecorded route matches these endpoints, region and blocked areas. Connect the routing API for an actual replan.",
        ],
      };
  s.setActiveRoute(result);
  useMissionStore.setState({
    replan: result.feasible ? "ready" : "failed",
    focus: Date.now(),
  });
}
