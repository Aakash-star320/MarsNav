import type { LayerState, RealAnalysis } from '../types/ui';

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

/** Layer labels once a real analysis exists: the layers it supplies say so, the rest stay simulated. */
export function realLabel(l: LayerMeta, real: RealAnalysis | null): LayerMeta {
  if (!real) return l;
  switch (l.id) {
    case 'elev': return { ...l, n: 'Elevation (real)', s: 'USGS MOLA 463 m global DEM', r: '463 m cells' };
    case 'slope': return { ...l, n: 'Slope (real)', s: 'Derived from the MOLA elevation', r: '463 m cells' };
    case 'haz': return { ...l, n: 'Steeper than your limit (real)', s: 'Cells above the maximum slope setting', r: '463 m cells' };
    case 'spec': return real.layers.science ? { ...l, n: 'Hydrated-mineral evidence (real)', s: 'CRISM summary parameters, heuristic screen', r: '18-36 m pixels', na: false } : l;
    default: return l;
  }
}
