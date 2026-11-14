import { create } from 'zustand';
import type { DataState, Mode, PanelKey, Pick, Pt, Region, Tab, Target } from '../types/ui';
import { STAGES, discoverTargets, planMission, planRoutes, summarizeRegion } from '../mocks/mock';
import { combined } from '../utils/derive';
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
let navTimer: number | undefined;

const initial: DataState = {
  mode: 'route', pick: null, start: null, dest: null, base: { x: 120, y: 360 }, wps: [], region: null,
  cats: { elev: true, slope: true, rough: true, haz: true, spec: true, therm: true },
  targets: [], summary: null, routes: [], sel: 0, mission: null,
  preset: 'bal', ret: true, slope: 20, maxd: 50, oxy: 4, res: 30, exam: 20, maxSites: 3, obj: 'Hydrated minerals',
  obs: [], prev: null, nav: null, tab: 'elev', focus: null, online: true, cache: false,
  job: null, err: '', stale: false, selT: null,
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
    setRegion: (r) => set({ region: r, pick: null, summary: null, targets: [] }),
    useVisibleMap: () => set({ region: FULL_MAP, pick: null, summary: null }),

    analyze: () => {
      const s = get();
      if (!s.region) { set({ err: 'Select a region first: drag on the map, or press Use visible map.' }); return; }
      const region = s.region;
      runJob('Analyze Region', [0, 1, 2, 3, 4, 5, 8], () => {
        set({ targets: discoverTargets(region), summary: summarizeRegion(region, get().slope) });
        openPanels(true, false);
      });
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
        pan: { ...s.pan, R: false, B: false }, start: null, dest: null, wps: [], region: null, targets: [], summary: null,
        routes: [], mission: null, obs: [], prev: null, focus: null, err: '', stale: false, selT: null,
        pick: s.mode === 'analyze' ? 'region' : null,
      });
    },
    cancelJob: () => { window.clearInterval(jobTimer); set({ job: null, err: 'Cancelled. Nothing was changed.' }); },
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
      set({ pick: null });
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
