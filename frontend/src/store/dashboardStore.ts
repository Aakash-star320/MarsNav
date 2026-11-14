import { create } from 'zustand';
import type { ChatAction, ChatCard, ChatMsg, DataState, Mode, PanelKey, Pick, Pt, Region, Tab, Target } from '../types/ui';
import { STAGES, discoverTargets, planMission, planRoutes } from '../mocks/mock';
import { combined } from '../utils/derive';
import { useMissionStore } from './missionStore';
import { PLANNING_AREA, autoTerrainRegion, getViewport } from '../utils/viewport';
import { API_BASE, AnalysisError, cancelAnalysis, createAnalysis, fetchMapPackage, waitForAnalysis } from '../api/analysis';
import { regionToBounds, toDashboardTarget } from '../api/mapping';
import { KM_PER_PX, WALK_KMH, lonLatToPx, pxToLonLat, regionZoom } from '../utils/geo';
import { buildMissionRequest, planMissionRemote, toDashboardMission } from '../api/missions';
import { RoutingError, buildRouteRequest, conflictText, guideRoute, obstacleToBlockedArea, planRoute, replanRoute, toDashboardRoutes } from '../api/routing';
import { askAssistant, fetchAssistantStatus, toChatMessage } from '../api/assistant';
import { defaultLayers } from '../utils/layers';

export interface Actions {
  setMode: (m: Mode) => void;
  setPick: (p: Pick | null) => void;
  setField: <K extends keyof DataState>(k: K, v: DataState[K]) => void;
  toggleCat: (k: keyof DataState['cats']) => void;
  toggleLayer: (id: string) => void;
  setOpacity: (id: string, op: number) => void;
  setRegion: (r: Region | null) => void;
  useVisibleMap: () => void;
  analyze: () => void;
  /** Reads real elevation for the selected region, or for the area on screen, so the 3D view works without a manual analysis. */
  analyzeTerrainView: () => void;
  generate: () => void;
  plan: () => void;
  reset: () => void;
  cancelJob: () => void;
  dismissError: () => void;
  clearWps: () => void;
  selectRoute: (i: number) => void;
  setTab: (t: Tab) => void;
  selectTarget: (id: string) => void;
  targetAsDest: (id: string) => void;
  targetAsWp: (id: string) => void;
  askAboutTarget: (id: string) => void;
  gotoStep: (i: number) => void;
  focusWarning: (at?: Pt) => void;
  setFocus: (p: Pt | null) => void;
  toggleOnline: () => void;
  toggleAi: () => void;
  refreshAssistant: () => void;
  /** Asks the routing service what to do next at a position on the followed route. */
  refreshGuide: (pos: Pt, headingDeg: number) => void;
  clearChat: () => void;
  showOnMap: (a: ChatAction) => void;
  setAiDraft: (v: string) => void;
  sendChat: (q: string) => void;
  navStart: () => void;
  navPause: () => void;
  navAdvance: (steps?: number) => void;
  navEnd: () => void;
  replan: () => void;
  mapPick: (p: Pt) => void;
  togglePanel: (k: PanelKey) => void;
  setPanelHeight: (h: number) => void;
  openPanels: (right: boolean, bottom: boolean) => void;
  addPackage: () => void;
  removePackage: (i: number) => void;
}
export type Store = DataState & Actions;

const FULL_MAP: Region = { x: 0, y: 0, w: 800, h: 500 };
const CONSTRAINT_KEYS = new Set<string>(['slope', 'oxy', 'res', 'exam', 'maxSites', 'maxd', 'preset', 'ret', 'obj']);
let jobTimer: number | undefined;
let realRunToken = 0;          // bumped on cancel so a late reply from an abandoned analysis is ignored
let navTimer: number | undefined;

const initial: DataState = {
  mode: 'route', pick: null, start: null, dest: null, base: { x: 120, y: 360 }, wps: [], region: null,
  cats: { elev: true, slope: true, rough: true, haz: true, spec: true, therm: true },
  targets: [], summary: null, routes: [], sel: 0, mission: null,
  preset: 'bal', ret: true, slope: 20, maxd: 50, oxy: 4, res: 30, exam: 20, maxSites: 3, obj: 'Hydrated minerals',
  obs: [], prev: null, nav: null, tab: 'elev', focus: null, online: true, cache: false,
  job: null, err: '', stale: false, selT: null, real: null,
  pk: [{ n: 'Jezero region package (demo)', sz: '148 MB', st: 'Downloaded', up: '2026-11-12' }],
  pan: { L: true, R: false, B: false }, bh: 260, adv: false, lyOpen: false,
  layers: defaultLayers(), chat: [], aiOpen: false, aiDraft: '', aiBar: null, focusZoom: null, assistantMode: null, assistantModel: null, pendingQ: null, routeSource: 'simulated', missionSource: 'simulated', routeNotes: [], guideText: null,
};

export const useStore = create<Store>((set, get) => {
  const openPanels = (right: boolean, bottom: boolean) => {
    const p = get().pan;
    set({ pan: { ...p, R: p.R || right, B: p.B || bottom } });
  };

  const clearResults = () => {
    get().navEnd();
    set({ routes: [], mission: null, prev: null });
  };

  /** Simulated backend job. Replace with polling of real job status. */
  const runJob = (title: string, idx: number[], done: () => void) => {
    if (get().job) return;
    const stages = idx.map((i) => STAGES[i]);
    set({ job: { title, stages, i: 0 }, err: '' });
    jobTimer = window.setInterval(() => {
      const s = get(), j = s.job;
      if (!j) return;
      if (stages[j.i] === 'Download' && !s.cache && !s.online) {
        window.clearInterval(jobTimer);
        set({ job: null, err: 'Download failed: you are offline and no cached package covers this region. Go online or prepare a mission package first.' });
        return;
      }
      const next = j.i + 1;
      if (next >= stages.length) {
        window.clearInterval(jobTimer);
        set({ job: null, cache: true });
        done();
        return;
      }
      set({ job: { ...j, i: next } });
    }, 450);
  };

  const BACKEND_STAGE: Record<string, number> = { queued: 0, discovery: 0, selection: 1, downloading: 2, preprocessing: 3, terrain: 4, science: 5 };

  /** Map action that frames a whole region (zoom chosen so the region spans most of the screen). */
  const regionAction = (r: Region): ChatAction => ({ label: 'Show region on map', at: { x: r.x + r.w / 2, y: r.y + r.h / 2 }, zoom: regionZoom(r) });
  let chatWait = false;     // set when the assistant started an analysis, so it can report the outcome in the chat
  const botSays = (m: ChatMsg) => set((s) => ({ chat: [...s.chat, m], aiBar: s.aiOpen ? null : m.r }));
  const runRealAnalysis = async (region: Region, terrainOnly = false) => {
    const token = ++realRunToken;
    const alive = () => token === realRunToken;
    const spec = !terrainOnly && get().cats.spec;
    const stages = ['Plan region', 'Select products', 'Read elevation', 'Validate', 'Derive terrain', ...(spec ? ['Search CRISM'] : []), 'Complete'];
    set({ job: { title: terrainOnly ? 'Reading terrain' : 'Analyze Region', stages, i: 0, real: true }, err: '' });
    try {
      const created = await createAnalysis(regionToBounds(region), spec ? 'find hydrated minerals' : 'terrain overview', 'Dashboard region');
      if (!alive()) { void cancelAnalysis(created.id).catch(() => undefined); return; }
      set((s) => ({ job: s.job ? { ...s.job, id: created.id } : s.job }));
      const done = await waitForAnalysis(created.id, (j) => {
        if (!alive()) return;
        const i = j.stage === 'completed' ? stages.length - 1 : Math.min(BACKEND_STAGE[j.stage] ?? 0, stages.length - 2);
        set((s) => ({ job: s.job ? { ...s.job, i } : s.job }));
      });
      if (!alive()) return;
      const pkg = await fetchMapPackage(created.id, get().slope);
      if (!alive()) return;
      const stats = pkg.statistics, el = pkg.layers.find((l) => l.layer.kind === 'elevation'), sl = pkg.layers.find((l) => l.layer.kind === 'slope');
      if (!stats || !el || !sl) throw new AnalysisError('The analysis returned no terrain layers.');
      const sci = pkg.layers.find((l) => l.layer.kind === 'science');
      const layer = (l: { layer: { uri: string; bounds: import('../types/contracts').BoundingBox } }) => ({ href: l.layer.uri, bounds: l.layer.bounds });
      set((s) => ({
        job: null, cache: true, err: '',
        real: { id: created.id, missionId: created.mission_id, hazardBase: API_BASE + '/analyses/' + created.id + '/layers/hazard.png', stats, notes: pkg.notes, warnings: done.warnings,
                layers: { elevation: layer(el), slope: layer(sl), science: sci ? layer(sci) : undefined } },
        summary: { w: region.w * KM_PER_PX, h: region.h * KM_PER_PX, mn: stats.elevation_min_m ?? 0, mx: stats.elevation_max_m ?? 0,
                   sl: stats.slope_mean_deg ?? 0, hz: 100 * (stats.slope_exceedance_fraction ?? 0) },
        targets: (pkg.science_targets ?? []).map(toDashboardTarget),
        layers: { ...s.layers, elev: { ...s.layers.elev, on: true }, ...(sci ? { spec: { ...s.layers.spec, on: true } } : {}) },
      }));
      try {                                   // the 3D view reads the same real terrain
        const ms = useMissionStore.getState();
        ms.setLayers(pkg.layers);
        if (el) { ms.setLayerVisibility(el.layer.id, true); ms.setLayerOpacity(el.layer.id, 0.4); }   // light tint over the imagery in 3D
        // Low-relief areas look flat at true scale, so exaggerate the height to show the shape (the 3D view says how much).
        const relief = Math.max(1, (stats.elevation_max_m ?? 0) - (stats.elevation_min_m ?? 0)), width = Math.max(region.w, region.h) * KM_PER_PX * 1000;
        useMissionStore.setState({ dem: pkg.dem ?? undefined, focus: Date.now(), exaggeration: Math.max(1, Math.min(10, Math.round((0.12 * width) / relief))) });
      } catch (e3d) { console.warn('[analysis] 3D terrain not loaded:', (e3d as Error).message); }
      const viaChat = chatWait;
      chatWait = false;
      if (!viaChat) openPanels(true, false);       // a chat-started analysis answers in the chat, so the side panel stays out of the way
      else {
        const found = get().targets;
        const f1 = (v: number | null | undefined, d = 0) => (v == null ? 'n/a' : v.toFixed(d));
        const card: ChatCard = {
          stats: [
            ['Area', `${(region.w * KM_PER_PX).toFixed(1)} × ${(region.h * KM_PER_PX).toFixed(1)} km`],
            ['Valid data', `${f1(stats.valid_percent)}%`],
            ['Elevation', `${f1(stats.elevation_min_m)} to ${f1(stats.elevation_max_m)} m`],
            ['Mean slope', `${f1(stats.slope_mean_deg, 1)}°`],
            ['Max slope', `${f1(stats.slope_max_deg, 1)}°`],
            [`Steeper than ${stats.slope_limit_deg ?? get().slope}°`, `${f1(100 * (stats.slope_exceedance_fraction ?? 0), 1)}% of cells`],
          ],
          targets: found.map((t) => ({ id: t.id, label: t.label ?? t.id, score: t.score, conf: t.conf, evidence: t.evidence?.[0], at: { x: t.x, y: t.y } })),
          warnings: [...done.warnings, ...pkg.notes.filter((n) => !done.warnings.includes(n))],
        };
        botSays({
          u: '', r: found.length
            ? `Analysis finished. ${found.length} hydrated-mineral candidate${found.length > 1 ? 's' : ''} met the screening rule. These are heuristic screens of CRISM summary parameters, not identified minerals.`
            : 'Analysis finished. No candidate met the rule in the covered part of the area. That is not evidence that hydrated minerals are absent.',
          card, actions: [regionAction(region), { label: 'Open full details', open: 'results' }],
        });
      }
    } catch (e) {
      if (!alive()) return;
      const err = e as AnalysisError;
      const msg = e instanceof TypeError ? 'Cannot reach the analysis service. Start the backend and try again.'
        : err.code === 'area_limit' ? 'That region is too large for one analysis. Select a smaller area.'
        : err.code === 'cancelled' ? 'Cancelled. Nothing was changed.' : 'Analysis failed: ' + err.message;
      set({ job: null, err: msg });
      if (chatWait) { chatWait = false; botSays({ u: '', r: msg, err: true }); }
    }
  };

  const applyRoutes = (from: Pt) => {
    const s = get();
    if (!s.dest) return;
    const prev = s.routes.length ? combined(s)?.s.p ?? null : null;
    const routes = planRoutes({ from, dest: s.dest, wps: s.wps, base: s.base, ret: s.ret, slope: s.slope, obs: s.obs });
    if (!routes.length) {
      set({ routes: [], prev, err: 'No feasible route: reported obstacles block every candidate path. Remove an obstacle or move the destination.' });
      return;
    }
    set({ routes, prev, sel: Math.max(0, routes.findIndex((r) => r.k === s.preset)), err: '', routeSource: 'simulated', routeNotes: [], guideText: null });
    openPanels(true, true);
  };

  // -- real routes: planned by the routing service on the analysed terrain --------------------------------------
  let routeToken = 0;
  let routeBasis: { preset: string; start: Pt; obs: number } | null = null;   // what the current real routes were planned for
  const analysedRect = (r: NonNullable<DataState['real']>) => {
    const b = r.layers.elevation.bounds, a = lonLatToPx({ latitude_deg: b.north_deg, longitude_deg_east: b.west_deg_east }), z = lonLatToPx({ latitude_deg: b.south_deg, longitude_deg_east: b.east_deg_east });
    return { x0: a.x, y0: a.y, x1: z.x, y1: z.y };
  };
  const insideRect = (p: Pt, r: { x0: number; y0: number; x1: number; y1: number }) => p.x >= r.x0 && p.x <= r.x1 && p.y >= r.y0 && p.y <= r.y1;

  const runRealRoutes = async (from: Pt) => {
    const s = get(), real = s.real, dest = s.dest;
    if (!real || !real.missionId || !dest) return;
    const token = ++routeToken;
    const alive = () => token === routeToken;
    set({ job: { title: 'Generate Routes', stages: ['Plan on the real terrain', 'Compare routes', 'Done'], i: 0, real: true }, err: '' });
    const inputs = { missionId: real.missionId, analysisId: real.id, start: from, dest, wps: s.wps, base: s.base, preset: s.preset, slope: s.slope, ret: s.ret, maxKm: s.maxd, oxyH: s.oxy,
                     reserveMin: s.res, examMin: s.exam, speedMPerMin: (WALK_KMH * 1000) / 60, obs: s.obs };
    try {
      const cur = s.routes[s.sel]?.src, added = s.obs.slice(routeBasis?.obs ?? 0).map(obstacleToBlockedArea);
      const canReplan = !!cur && s.routeSource === 'real' && added.length > 0 && routeBasis?.preset === s.preset && routeBasis.start.x === from.x && routeBasis.start.y === from.y;
      let res;
      if (canReplan && cur) {
        try { res = await replanRoute(cur.replanId, { original_route_id: cur.replanId, analysis_id: real.id, original_request_version: cur.version, blocked_areas: added }); }
        catch (e) { if (e instanceof RoutingError && (e.status === 404 || e.status === 409)) res = await planRoute(buildRouteRequest(inputs)); else throw e; }   // the service forgot the route (restart): plan again
      } else res = await planRoute(buildRouteRequest(inputs));
      if (!alive()) return;
      const prev = s.routes.length ? combined(s)?.s.p ?? null : null;
      const routes = toDashboardRoutes(res, s.preset, { slope: s.slope, speed: inputs.speedMPerMin, ret: s.ret, dest });
      if (!res.feasible || !routes.length) {
        set({ job: null, routes: [], prev, err: 'No feasible route: ' + conflictText(res), routeSource: 'real', routeNotes: res.warnings });
        return;
      }
      routeBasis = { preset: s.preset, start: from, obs: s.obs.length };
      const notes = res.warnings;
      set({ job: null, routes, prev, sel: Math.max(0, routes.findIndex((r) => r.k === s.preset)), err: '', routeSource: 'real', routeNotes: notes, guideText: null });
      openPanels(true, true);
    } catch (e) {
      if (!alive()) return;
      set({ job: null, err: e instanceof TypeError ? 'Cannot reach the routing service. Start the backend and try again.' : 'Route planning failed: ' + (e as Error).message });
    }
  };

  /** True when routes should come from the routing service: an analysis exists and the stops fit the contract (ten waypoints at most). */
  const realRoutesFor = (s: DataState) => !!s.real && s.wps.length <= 10;
  /** Why a set of points cannot be sent to the routing service, or null when all of them lie inside the analysed area. */
  const outsideAnalysis = (s: DataState, from: Pt): string | null => {
    if (!s.real || !s.dest) return null;
    const area = analysedRect(s.real);
    if (!insideRect(from, area) || !insideRect(s.dest, area)) return 'Start and Destination must both be inside the analysed area (the teal box): real routes only exist on terrain that has been analysed. Move them, or analyze a larger area.';
    if (s.wps.some((w) => !insideRect(w, area))) return 'Every waypoint must be inside the analysed area (the teal box). Move or clear the waypoints outside it.';
    if (s.ret && !insideRect(s.base, area)) return 'The Base must be inside the analysed area (the teal box) for a return trip. Move the Base, or turn off Return to base.';
    return null;
  };

  // -- real mission: the routing service picks real science targets and routes every leg on the analysed terrain ----
  let missionToken = 0;
  const runRealMission = async (from: Pt) => {
    const s = get(), real = s.real;
    if (!real || !real.missionId) return;
    const token = ++missionToken;
    set({ job: { title: 'Plan Mission', stages: ['Choose targets on the real terrain', 'Route each leg', 'Done'], i: 0, real: true }, err: '' });
    try {
      const res = await planMissionRemote(buildMissionRequest({ missionId: real.missionId, analysisId: real.id, start: from, base: s.base, targetIds: s.targets.map((t) => t.id),
        slope: s.slope, maxKm: s.maxd, oxyH: s.oxy, reserveMin: s.res, examMin: s.exam, maxSites: s.maxSites, obs: s.obs }));
      if (token !== missionToken || !get().job) return;            // superseded or cancelled while the service was working
      const prev = s.mission?.feasible ? combined(s)?.s.p ?? null : null;
      const mission = toDashboardMission(res, get().targets, { slope: s.slope });
      set({ job: null, mission, prev, err: mission.feasible ? '' : s.err, missionSource: 'real' });
      openPanels(true, mission.feasible);
    } catch (e) {
      if (token !== missionToken) return;
      set({ job: null, err: e instanceof TypeError ? 'Cannot reach the routing service. Start the backend and try again.' : 'Mission planning failed: ' + (e as Error).message });
    }
  };

  const applyMission = (from: Pt) => {
    const s = get();
    const prev = s.mission?.feasible ? combined(s)?.s.p ?? null : null;
    const mission = planMission({ from, base: s.base, targets: s.targets, oxy: s.oxy, res: s.res, exam: s.exam, maxSites: s.maxSites, slope: s.slope, maxd: s.maxd, obs: s.obs });
    set({ mission, prev, err: mission.feasible ? '' : s.err, missionSource: 'simulated' });
    openPanels(true, mission.feasible);
  };

  return {
    ...initial,

    setMode: (m) => set({ mode: m, pick: m === 'analyze' ? 'region' : null, err: '', stale: false }),
    setPick: (p) => set({ pick: p }),
    setField: (k, v) => {
      const s = get();
      set({ [k]: v } as unknown as Partial<Store>);
      if (CONSTRAINT_KEYS.has(k as string) && (s.routes.length || s.mission)) set({ stale: true });
    },
    toggleCat: (k) => set((s) => ({ cats: { ...s.cats, [k]: !s.cats[k] } })),
    toggleLayer: (id) => set((s) => ({ layers: { ...s.layers, [id]: { ...s.layers[id], on: !s.layers[id].on } } })),
    setOpacity: (id, op) => set((s) => ({ layers: { ...s.layers, [id]: { ...s.layers[id], op } } })),
    setRegion: (r) => set({ region: r, pick: null, summary: null, targets: [], real: null }),
    useVisibleMap: () => set({ region: FULL_MAP, pick: null, summary: null, real: null }),

    analyze: () => {
      const s = get();
      if (!s.region) { set({ err: 'Select a region first: drag on the map, or press Use visible map.' }); return; }
      if (s.job) return;
      if (!s.online) { set({ err: 'You are offline. Region analysis reads real data from NASA/USGS sources and needs network access.' }); return; }
      void runRealAnalysis(s.region);
    },
    analyzeTerrainView: () => {
      const s = get();
      if (s.job || s.real) return;
      if (!s.online) { set({ err: 'You are offline. The 3D terrain reads real elevation from USGS and needs network access.' }); return; }
      let region = s.region;
      if (!region) {
        region = autoTerrainRegion(getViewport() ?? PLANNING_AREA);
        set({ region, pick: null });
      }
      void runRealAnalysis(region, true);
    },
    generate: () => {
      const s = get();
      set({ stale: false });
      if (!s.start || !s.dest) { set({ err: 'Set both a Start and a Destination first. Use Set on map, or choose a science target.' }); return; }
      if (realRoutesFor(s) && s.real) {
        if (!s.online) { set({ err: 'You are offline. Real routes come from the routing service and need the backend.' }); return; }
        const why = outsideAnalysis(s, s.start);
        if (why) { set({ err: why }); return; }
        void runRealRoutes(s.start);
        return;
      }
      runJob('Generate Routes', [0, 1, 2, 3, 4, 6, 8], () => { const st = get(); if (st.start) applyRoutes(st.start); });
    },
    plan: () => {
      set({ stale: false });
      const rs = get();
      if (rs.real && rs.targets.length > 0 && rs.online && insideRect(rs.base, analysedRect(rs.real))) { void runRealMission(rs.base); return; }   // otherwise the simulated planner, labelled simulated
      runJob('Plan Mission', [0, 1, 2, 3, 4, 5, 6, 7, 8], () => {
        const s = get();
        if (!s.targets.length) set({ targets: discoverTargets(s.region ?? { x: 20, y: 20, w: 760, h: 460 }) });
        applyMission(get().base);
      });
    },
    reset: () => {
      get().navEnd();
      const s = get();
      set({
        pan: { ...s.pan, R: false, B: false }, start: null, dest: null, wps: [], region: null, targets: [], summary: null, real: null,
        routes: [], mission: null, obs: [], prev: null, focus: null, err: '', stale: false, selT: null, routeSource: 'simulated', missionSource: 'simulated', routeNotes: [], guideText: null,
        pick: s.mode === 'analyze' ? 'region' : null,
      });
    },
    cancelJob: () => {
      window.clearInterval(jobTimer);
      const j = get().job;
      if (j?.real) { realRunToken++; if (j.id) void cancelAnalysis(j.id).catch(() => undefined); }
      set({ job: null, err: 'Cancelled. Nothing was changed.' });
    },
    dismissError: () => set({ err: '' }),
    clearWps: () => { set({ wps: [] }); clearResults(); },
    selectRoute: (i) => set({ sel: i, focus: null }),
    setTab: (t) => { set({ tab: t }); openPanels(false, true); },
    selectTarget: (id) => set((s) => ({ selT: id, focusZoom: null, focus: s.targets.find((t) => t.id === id) ?? null })),
    targetAsDest: (id) => {
      const t = get().targets.find((x) => x.id === id);
      if (!t) return;
      set((s) => ({ mode: 'route', dest: { x: t.x, y: t.y, id: t.id }, start: s.start ?? s.base }));
      clearResults();
    },
    targetAsWp: (id) => {
      const t = get().targets.find((x) => x.id === id);
      if (!t) return;
      set((s) => ({ mode: 'route', wps: [...s.wps, { x: t.x, y: t.y }] }));
      clearResults();
    },
    askAboutTarget: (id) => set({ aiOpen: true, aiBar: null, aiDraft: 'Tell me about ' + id }),
    gotoStep: (i) => {
      const s = get(), c = combined(s);
      if (!c) return;
      set({ focus: i < 0 ? s.base : c.sg[i].s.p[c.sg[i].s.p.length - 1] });
    },
    focusWarning: (at) => { if (at) set({ focus: at, focusZoom: null }); },
    setFocus: (p) => set({ focus: p, focusZoom: null }),
    toggleOnline: () => set((s) => ({ online: !s.online })),
    toggleAi: () => { set((s) => ({ aiOpen: !s.aiOpen, aiBar: null })); if (get().aiOpen) get().refreshAssistant(); },
    clearChat: () => set({ chat: [], aiDraft: '', aiBar: null, pendingQ: null }),
    /** Asks the backend which assistant is active (hosted Gemma model or rule-based). Unreachable counts as rule-based. */
    refreshAssistant: () => {
      fetchAssistantStatus()
        .then((st) => set({ assistantMode: st.mode, assistantModel: st.model ?? null }))
        .catch(() => set({ assistantMode: 'rule_based', assistantModel: null }));
    },
    /** Collapses the chat to a small bar and brings the item into view on the map. */
    showOnMap: (a) => a.open ? openPanels(true, false) : a.at && set((s) => ({ focus: a.at, focusZoom: a.zoom ?? null, selT: a.id ?? s.selT, aiOpen: false, aiBar: s.chat[s.chat.length - 1]?.r ?? 'Showing it on the map.' })),
    setAiDraft: (v) => set({ aiDraft: v }),

    navStart: () => {
      if (!combined(get())) return;
      window.clearInterval(navTimer);
      set({ nav: { i: 0, paused: false } });
      navTimer = window.setInterval(() => {
        const n = get().nav;
        if (n && !n.paused) get().navAdvance(1);
      }, 800);
    },
    navPause: () => set((s) => (s.nav ? { nav: { ...s.nav, paused: !s.nav.paused } } : {})),
    navAdvance: (steps = 5) => {
      const s = get(), c = combined(s);
      if (!s.nav || !c) return;
      set({ nav: { ...s.nav, i: Math.min(c.s.p.length - 1, s.nav.i + steps) } });
    },
    navEnd: () => { window.clearInterval(navTimer); set({ nav: null, focus: null }); },

    replan: () => {
      const s = get();
      set({ err: '' });
      let from: Pt | null = s.start;
      if (s.nav) {
        const c = combined(s);
        if (c) {
          const p = c.s.p[s.nav.i];
          from = { x: p.x, y: p.y };
          set({ start: from, nav: { ...s.nav, i: 0 } });
        }
      }
      if (s.mode === 'mission') applyMission(s.nav && from ? from : s.base);
      else if (s.dest && from) {
        if (realRoutesFor(s) && s.real) {
          const why = outsideAnalysis(s, from);
          if (why) { set({ err: why }); return; }
          void runRealRoutes(from);
        } else applyRoutes(from);
      }
    },
    refreshGuide: (pos, headingDeg) => {
      const s = get(), r = s.routes[s.sel];
      if (s.routeSource !== 'real' || !r?.src) return;
      const id = r.src.id, ll = pxToLonLat(pos);
      guideRoute(id, { latitude_deg: ll.latitude_deg, longitude_deg_east: ll.longitude_deg_east }, ((headingDeg % 360) + 360) % 360)
        .then((g) => { if (get().routes[get().sel]?.src?.id === id) set({ guideText: g.message }); })
        .catch(() => set({ guideText: null }));            // guidance is a convenience: the route and the HUD stay usable without it
    },

    mapPick: (p) => {
      const s = get(), k = s.pick;
      if (!k || k === 'region') return;
      const inFrame = p.x >= 0 && p.y >= 0 && p.x <= 800 && p.y <= 500;
      const inAnalysis = !!s.real && insideRect(p, analysedRect(s.real));      // real routes may go anywhere on the analysed terrain
      if (!inFrame && !inAnalysis) {
        set({ err: s.real ? 'That point is outside the analysed area (the teal box) and the planning frame. Real routes only exist on analysed terrain; click inside the teal box.' : 'That point is outside the planning area (the dashed frame, 16 × 10 km). Simulated routes only exist inside it; click inside the frame, or press Fit to see it.' });
        return;
      }
      set({ pick: null, err: '' });
      if (k === 'wp') { set({ wps: [...s.wps, p] }); clearResults(); }
      else if (k === 'obs') {
        set({ obs: [...s.obs, { x: p.x, y: p.y, r: 35 }] });
        if (s.routes.length || s.mission) get().replan();
      } else if (k === 'cur') {
        const c = combined(s);
        if (c) {
          let bi = 0;
          c.s.p.forEach((q, i) => { if (Math.hypot(q.x - p.x, q.y - p.y) < Math.hypot(c.s.p[bi].x - p.x, c.s.p[bi].y - p.y)) bi = i; });
          set({ nav: { i: bi, paused: s.nav ? s.nav.paused : true } });
        }
      } else { set({ [k]: p } as unknown as Partial<Store>); clearResults(); }
    },

    togglePanel: (k) => set((s) => ({ pan: { ...s.pan, [k]: !s.pan[k] } })),
    setPanelHeight: (h) => set({ bh: h }),
    openPanels,

    addPackage: () => {
      const s = get(), idx = s.pk.length;
      set({ pk: [...s.pk, { n: s.region ? 'Custom region package (demo)' : 'Current view package (demo)', sz: '0 MB', st: 'Downloading 0%', up: 'today' }] });
      let k = 0;
      const t = window.setInterval(() => {
        k += 20;
        set((st) => ({
          pk: st.pk.map((p, i) => (i === idx ? { ...p, sz: `${Math.floor(k * 1.4)} MB`, st: k >= 100 ? 'Downloaded' : `Downloading ${k}%` } : p)),
          ...(k >= 100 ? { cache: true } : {}),
        }));
        if (k >= 100) window.clearInterval(t);
      }, 500);
    },
    removePackage: (i) => set((s) => ({ pk: s.pk.filter((_, j) => j !== i) })),

    /** Mock assistant: maps text onto the same verified actions as the buttons. No LLM, and no coordinates are parsed from text. */
    sendChat: (q0) => {
      const q = q0.trim();
      if (!q) return;
      const say = (r: string, extra: { err?: boolean; note?: string; steps?: string[]; actions?: ChatAction[] } = {}) =>
        set((s) => ({ chat: [...s.chat, { u: q, r, ...extra }], aiDraft: '' }));
      if (!get().online) { say('Service unavailable: the assistant needs internet. Manual planning still works.', { err: true }); return; }
      const l = q.toLowerCase().replace(/\b(two|four)\b/g, (m) => (m === 'two' ? '2' : '4'));
      const askBackend = () => {
        const st = get();
        set({ pendingQ: q, aiDraft: '' });
        askAssistant(q, st.real?.id, st.region ? regionToBounds(st.region) : undefined)
          .then((resp) => set((s) => ({ chat: [...s.chat, { u: q, ...toChatMessage(resp, get().targets) }], pendingQ: null })))
          .catch((e: Error) => set((s) => ({
            chat: [...s.chat, { u: q, r: e instanceof TypeError ? 'I could not reach the assistant service. Start the backend and try again.' : e.message || 'The assistant could not answer.', err: true }],
            pendingQ: null,
          })));
      };
      // With a language model, questions (not commands) go straight to it; commands still run the checked UI actions below.
      if (get().assistantMode === 'gemma' && /\?|^(what|why|how|which|where|who|when|explain|tell|describe|is|are|does|do|can|could|show me|summari[sz]e)\b/.test(l)) { askBackend(); return; }
      const n = (l.match(/(\d+(\.\d+)?)/) || [])[1];
      const did: string[] = [];
      if (/why|important/.test(l) && /mineral/.test(l)) {
        say('Hydrated minerals form when rock interacts with water, so they point to past wet environments that may have preserved evidence of habitability.', { note: 'Demo answer. A real RAG reply would cite NASA sources here.' });
        return;
      }
      if (/slope/.test(l) && n) {
        set({ slope: +n });
        did.push(`Max slope set to ${n}°`);
        if (get().routes.length || get().mission) set({ stale: true });
      }
      if (/oxygen|hours|remaining/.test(l) && n && !/slope/.test(l)) { set({ oxy: +n }); did.push(`Oxygen set to ${n} h`); }
      if (/analy[sz]e/.test(l)) {
        set({ mode: 'analyze', pick: null });
        if (!get().region) set({ region: FULL_MAP });
        chatWait = true;
        get().analyze();
        if (get().err) chatWait = false;            // refused (offline, nothing selected): the error is shown and nothing will report back
        did.push('Started Analyze Region');
      } else if (/mineral|mission|sites/.test(l)) {
        set({ mode: 'mission', pick: null });
        get().plan();
        did.push('Started Plan Mission');
      } else if (/safest|route|return/.test(l)) {
        set({ mode: 'route', pick: null, ...(/safest/.test(l) ? { preset: 'safe' as const } : {}) });
        if (!get().start) set({ start: get().base });
        if (!get().dest) { say((did.length ? did.join('. ') + '. ' : '') + 'I need a destination first. Click one on the map or choose a target.'); return; }
        if (/return|remaining/.test(l) && get().routes.length) { get().replan(); did.push('Recalculated route'); }
        else { get().generate(); did.push('Started Generate Routes'); }
      }
      if (!did.length) { askBackend(); return; }       // not a command: let the assistant service answer (it states its limits itself)
const rg = get().region, acts: ChatAction[] = rg && did.some((d) => /Analyze/.test(d)) ? [regionAction(rg)] : [];
      say('Done. I applied these checked actions; I will report back here when it finishes.', { steps: did, actions: acts });
    },
  };
});

export type { Target };
