import type { BoundingBox } from './contracts';
import type { RegionStatistics } from '../api/analysis';
export interface Pt { x: number; y: number }
export interface Region { x: number; y: number; w: number; h: number }
export interface Obstacle extends Pt { r: number }
export type Mode = 'analyze' | 'route' | 'mission';
export type Pick = 'region' | 'start' | 'dest' | 'base' | 'wp' | 'obs' | 'cur';
export type Preset = 'short' | 'safe' | 'bal';
export type Tab = 'elev' | 'slope' | 'warn' | 'data' | 'off';
export type PanelKey = 'L' | 'R' | 'B';

export interface Stats {
  p: Pt[]; d: number; up: number; dn: number; mx: number; av: number;
  cum: number[]; el: number[]; sl: number[]; over: number[]; t: number;
}
export interface Target { id: string; cat: string; x: number; y: number; score: number; conf: string; label?: string; evidence?: string[]; rank?: string }
export interface Dest extends Pt { id?: string }
export interface Route { k: Preset; n: string; c: string; out: Stats; ret: Stats | null; bend: number }
export interface MissionLeg { t: Target; s: Stats }
export interface Mission {
  feasible: boolean; msg?: string; legs: MissionLeg[]; ret?: Stats;
  ex: { t: Target; r: string }[];
}
export interface Summary { w: number; h: number; mn: number; mx: number; sl: number; hz: number }
export interface Job { title: string; stages: string[]; i: number; real?: boolean; id?: string }
export interface RealLayer { href: string; bounds: BoundingBox }
/** A finished analysis from the backend: images placed by geographic bounds, and real statistics. */
export interface RealAnalysis {
  id: string; hazardBase: string;
  layers: { elevation: RealLayer; slope: RealLayer; roughness?: RealLayer; science?: RealLayer };
  stats: RegionStatistics; warnings: string[]; notes: string[];
}
export interface Nav { i: number; paused: boolean }
export interface Pkg { n: string; sz: string; st: string; up: string }
export interface ChatMsg { u: string; r: string; err?: boolean; note?: string }
export interface Warning { k: 'bad' | 'warn' | 'info'; t: string; at?: Pt }
export interface LayerState { on: boolean; op: number }
export type Cats = Record<'elev' | 'slope' | 'rough' | 'haz' | 'spec' | 'therm', boolean>;

/** Everything the dashboard and the map read/write. Single source of truth. */
export interface DataState {
  mode: Mode; pick: Pick | null;
  start: Pt | null; dest: Dest | null; base: Pt; wps: Pt[]; region: Region | null;
  cats: Cats; targets: Target[]; summary: Summary | null;
  routes: Route[]; sel: number; mission: Mission | null;
  preset: Preset; ret: boolean; slope: number; maxd: number; oxy: number; res: number;
  exam: number; maxSites: number; obj: string;
  obs: Obstacle[]; prev: Pt[] | null; nav: Nav | null;
  tab: Tab; focus: Pt | null; online: boolean; cache: boolean;
  job: Job | null; err: string; stale: boolean; selT: string | null;
  pk: Pkg[]; pan: Record<PanelKey, boolean>; bh: number; adv: boolean; lyOpen: boolean;
  real: RealAnalysis | null; layers: Record<string, LayerState>; chat: ChatMsg[]; aiOpen: boolean; aiDraft: string;
}
