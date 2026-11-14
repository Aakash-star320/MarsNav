// Client for the analysis endpoints: start a job, poll it, fetch the map package and load it into the
// shared mission store so the 2D/3D map shows real processed layers.
import type { BoundingBox } from '../types/contracts';
import type { Dem, MapLayer } from '../features/mars-map/types';
import { useMissionStore } from '../store/missionStore';

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000/api/v1';

export type AnalysisJob = {
  id: string; stage: string; progress_percent: number; message: string; warnings: string[]; error_code?: string | null;
};
export type MapPackage = { analysis_id: string; layers: MapLayer[]; dem?: Dem | null; notes: string[] };

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
  const { intervalMs = 1000, timeoutMs = 120_000 } = opts;
  const t0 = Date.now();
  for (;;) {
    const job = await json<AnalysisJob>(await fetch(`${API_BASE}/analyses/${id}`));
    onProgress?.(job);
    if (job.stage === 'completed') return job;
    if (job.stage === 'failed') throw new AnalysisError(job.message, job.error_code ?? undefined);
    if (Date.now() - t0 > timeoutMs) throw new AnalysisError('The analysis is taking longer than expected; check its status later.', 'timeout');
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export async function fetchMapPackage(id: string): Promise<MapPackage> {
  return json(await fetch(`${API_BASE}/analyses/${id}/map`));
}

/** Puts a map package into the mission store; the elevation layer starts visible. */
export function applyMapPackage(pkg: MapPackage) {
  const s = useMissionStore.getState();
  s.setLayers(pkg.layers);
  useMissionStore.setState({ dem: pkg.dem ?? undefined });
  const first = pkg.layers.find((l) => l.layer.kind === 'elevation') ?? pkg.layers[0];
  if (first) s.setLayerVisibility(first.layer.id, true);
}

/** Runs a full analysis for an area and shows the result on the map. Returns the job's warnings. */
export async function analyzeAreaOnMap(aoi: BoundingBox, onProgress?: (j: AnalysisJob) => void): Promise<string[]> {
  const created = await createAnalysis(aoi);
  const done = await waitForAnalysis(created.id, onProgress);
  applyMapPackage(await fetchMapPackage(created.id));
  return done.warnings;
}
