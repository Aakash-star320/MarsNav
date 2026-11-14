import type { LayerState } from '../types/ui';

export interface LayerMeta { id: string; n: string; s: string; r?: string; na?: boolean }

/** Layer metadata shown in the UI. Replace with metadata returned by the backend. */
export const LAYERS: LayerMeta[] = [
  { id: 'opt', n: 'Optical imagery', s: 'Demo (HiRISE/CTX-class)', r: '~1 m' },
  { id: 'elev', n: 'Elevation', s: 'Demo DEM (MOLA/HRSC-class)', r: '~20 m grid' },
  { id: 'slope', n: 'Slope', s: 'Derived from demo DEM', r: '~20 m' },
  { id: 'haz', n: 'Potential hazards', s: 'Slope above your limit', r: '~20 m' },
  { id: 'therm', n: 'Thermal', s: 'Demo (THEMIS-class), historical', r: 'coarse' },
  { id: 'spec', n: 'Mineral / spectral', s: 'Unavailable: no product downloaded. Missing coverage ≠ no minerals.', na: true },
  { id: 'cov', n: 'Data coverage', s: 'Detailed / moderate / coarse' },
];

export const defaultLayers = (): Record<string, LayerState> => ({
  opt: { on: true, op: 0.9 }, elev: { on: false, op: 0.6 }, slope: { on: false, op: 0.6 },
  haz: { on: false, op: 0.7 }, therm: { on: false, op: 0.5 }, spec: { on: false, op: 0.5 }, cov: { on: false, op: 0.45 },
});
