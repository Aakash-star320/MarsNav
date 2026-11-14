// Client for the analysis endpoints: start a job, poll it, fetch the map package and load it into the
// shared mission store so the 2D/3D map shows real processed layers.
import type { BoundingBox, ScienceTarget } from '../types/contracts';
import type { Dem, MapLayer } from '../features/mars-map/types';
import { useMissionStore } from '../store/missionStore';

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000/api/v1';

export type AnalysisJob = {
  id: string; mission_id?: string; stage: string; progress_percent: number; message: string; warnings: string[]; error_code?: string | null;
};
/** Descriptive statistics over valid cells (mirrors backend RegionStatistics). Not a safety assessment. */
export type RegionStatistics = {
  area_km2: number; rows: number; cols: number; cells_total: number; cells_valid: number; valid_percent: number;
  native_resolution_m?: number | null; cell_size_x_m: number; cell_size_y_m: number;
  elevation_min_m?: number | null; elevation_max_m?: number | null; elevation_mean_m?: number | null;
  slope_mean_deg?: number | null; slope_max_deg?: number | null; slope_p50_deg?: number | null; slope_p90_deg?: number | null; slope_p99_deg?: number | null;
  roughness_mean_m?: number | null; roughness_max_m?: number | null;
  slope_limit_deg: number; slope_denominator_cells: number; slope_exceedance_cells: number; slope_exceedance_fraction?: number | null;
  science_candidates: number; notes: string[];
};
export type MapPackage = { analysis_id: string; layers: MapLayer[]; dem?: Dem | null; statistics?: RegionStatistics | null; science_targets?: ScienceTarget[]; notes: string[] };

export class AnalysisError extends Error {
  constructor(message: string, readonly code?: string) { super(message); }
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { const b = await res.json(); detail = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail ?? b); } catch { /* keep status text */ }
    throw new AnalysisError(detail);
  }
  return res.json() as Promise<T>;
}

export async function createAnalysis(aoi: BoundingBox, objective = 'terrain overview', name = 'Selected area'): Promise<AnalysisJob> {
  return json(await fetch(`${API_BASE}/analyses`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mission_id: crypto.randomUUID(), objective, roi: { name, bounds: aoi, analysis_margin_m: 0 } }),
  }));
}

export async function waitForAnalysis(
  id: string, onProgress?: (j: AnalysisJob) => void, opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<AnalysisJob> {
  const { intervalMs = 400, timeoutMs = 120_000 } = opts;
  const t0 = Date.now();
  for (;;) {
    const job = await json<AnalysisJob>(await fetch(`${API_BASE}/analyses/${id}`));
    onProgress?.(job);
    if (job.stage === 'completed') return job;
    if (job.stage === 'failed') throw new AnalysisError(job.message, job.error_code ?? undefined);
    if (job.stage === 'cancelled') throw new AnalysisError(job.message, 'cancelled');
    if (Date.now() - t0 > timeoutMs) throw new AnalysisError('The analysis is taking longer than expected; check its status later.', 'timeout');
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/** Cancels a queued or running analysis; resolves quietly if it had already finished. */
export async function cancelAnalysis(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/analyses/${id}/cancel`, { method: 'POST' });
  if (!res.ok && res.status !== 409 && res.status !== 404) await json(res);
}

export async function fetchMapPackage(id: string, slopeLimitDeg?: number): Promise<MapPackage> {
  const q = slopeLimitDeg ? `?slope_limit_deg=${encodeURIComponent(slopeLimitDeg)}` : '';
  return json(await fetch(`${API_BASE}/analyses/${id}/map${q}`));
}

/** Puts a map package into the mission store; the elevation layer starts visible. */
export function applyMapPackage(pkg: MapPackage) {
  const s = useMissionStore.getState();
  s.setLayers(pkg.layers);
  useMissionStore.setState({ dem: pkg.dem ?? undefined, focus: Date.now() });
  try { s.setTargets(pkg.science_targets ?? []); } catch (e) { console.warn("[analysis] targets not loaded:", (e as Error).message); }
  const first = pkg.layers.find((l) => l.layer.kind === 'elevation') ?? pkg.layers[0];
  if (first) s.setLayerVisibility(first.layer.id, true);
}

export type AnalysisOutcome = { analysisId: string; warnings: string[]; statistics?: RegionStatistics | null; notes: string[] };

/** Runs a full analysis for an area and shows the result on the map. */
export async function analyzeAreaOnMap(aoi: BoundingBox, onProgress?: (j: AnalysisJob) => void, slopeLimitDeg = 12): Promise<AnalysisOutcome> {
  const created = await createAnalysis(aoi);
  const done = await waitForAnalysis(created.id, onProgress);
  const pkg = await fetchMapPackage(created.id, slopeLimitDeg);
  applyMapPackage(pkg);
  return { analysisId: created.id, warnings: done.warnings, statistics: pkg.statistics, notes: pkg.notes };
}
