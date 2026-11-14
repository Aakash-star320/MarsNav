import { create } from "zustand";
import type {
  BoundingBox,
  LonLat,
  RouteResult,
  ScienceTarget,
  BlockedArea,
  NavigationState,
} from "../types/contracts";
import type { Dem, MapLayer, Mode } from "../features/mars-map/types";
import {
  validatePoint,
  validateBounds,
  validateRoute,
  corners,
} from "../features/mars-map/geometry";
export type MissionState = {
  selectedPoint?: LonLat;
  selectedTargetId?: string;
  activeRoute?: RouteResult;
  targets: ScienceTarget[];
  base?: LonLat;
  destination?: LonLat;
  aoi?: BoundingBox;
  layers: MapLayer[];
  layerSettings: Record<string, { visible: boolean; opacity: number }>;
  layerStatus: Record<string, string>;
  dem?: Dem;
  alternatives: RouteResult[];
  blockedAreas: BlockedArea[];
  navigation?: NavigationState;
  playing: boolean;
  progress: number;
  view: "2d" | "3d";
  mode: Mode;
  first?: LonLat;
  draft?: BoundingBox;
  reason: string;
  error?: string;
  replan: "idle" | "pending" | "ready" | "failed";
  showAlternatives: boolean;
  focus: number;
  exaggeration: number;
  setSelectedPoint: (p: LonLat) => void;
  setSelectedTarget: (id?: string) => void;
  setActiveRoute: (r?: RouteResult) => void;
  setTargets: (t: ScienceTarget[]) => void;
  setBase: (p?: LonLat) => void;
  setDestination: (p?: LonLat) => void;
  setAoi: (b?: BoundingBox) => void;
  setLayers: (l: MapLayer[]) => void;
  setLayerVisibility: (id: string, v: boolean) => void;
  setLayerOpacity: (id: string, v: number) => void;
  setMode: (m: Mode) => void;
  pick: (p: LonLat) => void;
  confirm: () => void;
  cancel: () => void;
  setView: (v: "2d" | "3d") => void;
  reset: () => void;
};
const initial = {
  targets: [],
  layers: [],
  layerSettings: {},
  layerStatus: {},
  alternatives: [],
  blockedAreas: [],
  playing: false,
  progress: 0,
  view: "2d" as const,
  mode: "inspect" as const,
  reason: "",
  replan: "idle" as const,
  showAlternatives: true,
  focus: 0,
  exaggeration: 1,
  selectedPoint: undefined,
  selectedTargetId: undefined,
  activeRoute: undefined,
  base: undefined,
  destination: undefined,
  aoi: undefined,
  dem: undefined,
  navigation: undefined,
  first: undefined,
  draft: undefined,
  error: undefined,
};
const stale = {
  activeRoute: undefined,
  alternatives: [],
  navigation: undefined,
  playing: false,
  progress: 0,
  replan: "idle" as const,
};
export const useMissionStore = create<MissionState>((set, get) => ({
  ...initial,
  setSelectedPoint: (p) => {
    validatePoint(p);
    set({ selectedPoint: p });
  },
  setSelectedTarget: (id) => set({ selectedTargetId: id }),
  setActiveRoute: (r) => {
    if (r) validateRoute(r);
    set({ activeRoute: r, navigation: undefined, playing: false, progress: 0 });
  },
  setTargets: (targets) => {
    const ids = new Set();
    targets.forEach((t) => {
      validatePoint(t.location);
      if (ids.has(t.id)) throw Error("Duplicate target ID");
      ids.add(t.id);
    });
    set({
      targets,
      selectedTargetId: targets.some((t) => t.id === get().selectedTargetId)
        ? get().selectedTargetId
        : undefined,
    });
  },
  setBase: (base) => {
    if (base) validatePoint(base);
    set({ base, ...stale });
  },
  setDestination: (destination) => {
    if (destination) validatePoint(destination);
    set({ destination, ...stale });
  },
  setAoi: (aoi) => {
    if (aoi) validateBounds(aoi);
    set({
      aoi,
      ...stale,
      targets: [],
      selectedTargetId: undefined,
      layers: [],
      layerSettings: {},
      layerStatus: {},
      dem: undefined,
      blockedAreas: [],
    });
  },
  setLayers: (layers) => {
    const ids = new Set();
    layers.forEach((l) => {
      if (ids.has(l.layer.id)) throw Error("Duplicate layer ID");
      ids.add(l.layer.id);
    });
    set({
      layers,
      layerSettings: Object.fromEntries(
        layers.map((l) => [
          l.layer.id,
          get().layerSettings[l.layer.id] ?? { visible: false, opacity: 1 },
        ]),
      ),
      layerStatus: {},
    });
  },
  setLayerVisibility: (id, visible) => {
    if (!get().layers.some((l) => l.layer.id === id))
      throw Error("Unknown layer");
    set({
      layerSettings: {
        ...get().layerSettings,
        [id]: { ...get().layerSettings[id], visible },
      },
    });
  },
  setLayerOpacity: (id, opacity) => {
    if (!Number.isFinite(opacity) || opacity < 0 || opacity > 1)
      throw Error("Invalid opacity");
    if (!get().layers.some((l) => l.layer.id === id))
      throw Error("Unknown layer");
    set({
      layerSettings: {
        ...get().layerSettings,
        [id]: { ...get().layerSettings[id], opacity },
      },
    });
  },
  setMode: (mode) =>
    set({
      mode,
      first: undefined,
      draft: undefined,
      error: undefined,
      reason: "",
    }),
  cancel: () =>
    set({
      mode: "inspect",
      first: undefined,
      draft: undefined,
      error: undefined,
      reason: "",
    }),
  pick: (p) => {
    try {
      validatePoint(p);
      set({ selectedPoint: p, error: undefined });
      const s = get();
      if (s.mode === "base") {
        s.setBase(p);
        s.cancel();
      } else if (s.mode === "destination") {
        s.setDestination(p);
        s.cancel();
      } else if (s.mode === "aoi" || s.mode === "blocked") {
        if (s.draft) return;
        if (!s.first) set({ first: p });
        else set({ draft: corners(s.first, p) });
      }
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
  confirm: () => {
    const s = get();
    if (!s.draft) return;
    if (s.mode === "blocked") {
      if (!s.reason.trim() || s.reason.trim().length > 500) {
        set({ error: "Enter a reason (1–500 characters)." });
        return;
      }
      const area = {
        id: crypto.randomUUID(),
        bounds: s.draft,
        reason: s.reason.trim(),
      };
      set({
        blockedAreas: [...s.blockedAreas, area],
        replan: "pending",
        playing: false,
        navigation: undefined,
      });
    } else s.setAoi(s.draft);
    get().cancel();
  },
  setView: (view) =>
    set({
      view,
      first: undefined,
      draft: undefined,
      mode: "inspect",
      error: undefined,
    }),
  reset: () => set({ ...initial }),
}));
