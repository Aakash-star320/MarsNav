import type { LayerState } from '../types/ui';

export interface LayerMeta { id: string; n: string; s: string; r?: string; na?: boolean }

/** Layer metadata shown in the UI. Replace with metadata returned by the backend. */
export const LAYERS: LayerMeta[] = [
  { id: 'opt', n: 'Mars surface imagery', s: 'NASA Mars Trek, Viking MDIM colour mosaic (real imagery)', r: '232 m/px' },
  { id: 'elev', n: 'Elevation', s: 'Simulated demo terrain (not the imagery below)', r: '~20 m grid' },
  { id: 'slope', n: 'Slope', s: 'Simulated, derived from the demo terrain', r: '~20 m' },
  { id: 'haz', n: 'Potential hazards', s: 'Slope above your limit', r: '~20 m' },
  { id: 'therm', n: 'Thermal', s: 'Simulated demo layer', r: 'coarse' },
  { id: 'spec', n: 'Mineral / spectral', s: 'Unavailable: no product downloaded. Missing coverage ≠ no minerals.', na: true },
  { id: 'cov', n: 'Data coverage', s: 'Detailed / moderate / coarse' },
];

export const defaultLayers = (): Record<string, LayerState> => ({
  opt: { on: true, op: 0.9 }, elev: { on: false, op: 0.6 }, slope: { on: false, op: 0.6 },
  haz: { on: false, op: 0.7 }, therm: { on: false, op: 0.5 }, spec: { on: false, op: 0.5 }, cov: { on: false, op: 0.45 },
});
