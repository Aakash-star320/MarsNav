import { create } from 'zustand';
import type { DataState, Mode, PanelKey, Pick, Pt, Region, Tab, Target } from '../types/ui';
import { STAGES, discoverTargets, planMission, planRoutes } from '../mocks/mock';
import { combined } from '../utils/derive';
import { useMissionStore } from './missionStore';
import { autoTerrainRegion, getViewport } from '../utils/viewport';
import { API_BASE, AnalysisError, cancelAnalysis, createAnalysis, fetchMapPackage, waitForAnalysis } from '../api/analysis';
import { regionToBounds, toDashboardTarget } from '../api/mapping';
import { KM_PER_PX } from '../utils/geo';
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
  layers: defaultLayers(), chat: [], aiOpen: false, aiDraft: '',
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
        real: { id: created.id, hazardBase: API_BASE + '/analyses/' + created.id + '/layers/hazard.png', stats, notes: pkg.notes, warnings: done.warnings,
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
      openPanels(true, false);
    } catch (e) {
      if (!alive()) return;
      const err = e as AnalysisError;
      const msg = e instanceof TypeError ? 'Cannot reach the analysis service. Start the backend and try again.'
        : err.code === 'area_limit' ? 'That region is too large for one analysis. Select a smaller area.'
        : err.code === 'cancelled' ? 'Cancelled. Nothing was changed.' : 'Analysis failed: ' + err.message;
      set({ job: null, err: msg });
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
    set({ routes, prev, sel: Math.max(0, routes.findIndex((r) => r.k === s.preset)), err: '' });
    openPanels(true, true);
  };

  const applyMission = (from: Pt) => {
    const s = get();
    const prev = s.mission?.feasible ? combined(s)?.s.p ?? null : null;
    const mission = planMission({ from, base: s.base, targets: s.targets, oxy: s.oxy, res: s.res, exam: s.exam, maxSites: s.maxSites, slope: s.slope, maxd: s.maxd, obs: s.obs });
    set({ mission, prev, err: mission.feasible ? '' : s.err });
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
        const v = getViewport();
        if (!v) return;
        region = autoTerrainRegion(v);
        set({ region, pick: null });
      }
      void runRealAnalysis(region, true);
    },
    generate: () => {
      const s = get();
      set({ stale: false });
      if (!s.start || !s.dest) { set({ err: 'Set both a Start and a Destination first. Use Set on map, or choose a science target.' }); return; }
      runJob('Generate Routes', [0, 1, 2, 3, 4, 6, 8], () => { const st = get(); if (st.start) applyRoutes(st.start); });
    },
    plan: () => {
      set({ stale: false });
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
        routes: [], mission: null, obs: [], prev: null, focus: null, err: '', stale: false, selT: null,
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
    selectTarget: (id) => set((s) => ({ selT: id, focus: s.targets.find((t) => t.id === id) ?? null })),
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
    askAboutTarget: (id) => set({ aiOpen: true, aiDraft: 'Tell me about ' + id }),
    gotoStep: (i) => {
      const s = get(), c = combined(s);
      if (!c) return;
      set({ focus: i < 0 ? s.base : c.sg[i].s.p[c.sg[i].s.p.length - 1] });
    },
    focusWarning: (at) => { if (at) set({ focus: at }); },
    setFocus: (p) => set({ focus: p }),
    toggleOnline: () => set((s) => ({ online: !s.online })),
    toggleAi: () => set((s) => ({ aiOpen: !s.aiOpen })),
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
      else if (s.dest && from) applyRoutes(from);
    },

    mapPick: (p) => {
      const s = get(), k = s.pick;
      if (!k || k === 'region') return;
      if (p.x < 0 || p.y < 0 || p.x > 800 || p.y > 500) {
        set({ err: 'That point is outside the planning area (the dashed frame, 16 × 10 km). Simulated routes only exist inside it; click inside the frame, or press Fit to see it.' });
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
      const say = (r: string, extra: { err?: boolean; note?: string } = {}) =>
        set((s) => ({ chat: [...s.chat, { u: q, r, ...extra }], aiDraft: '' }));
      if (!get().online) { say('Service unavailable: the hosted assistant needs internet. Manual planning still works.', { err: true }); return; }
      const l = q.toLowerCase().replace(/\b(two|four)\b/g, (m) => (m === 'two' ? '2' : '4'));
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
        get().analyze();
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
      if (!did.length) { say('I can analyze a region, plan a route or mission, change limits, or explain science. Try a suggestion.'); return; }
      say('Verified actions applied: ' + did.join('; ') + '.');
    },
  };
});

export type { Target };
