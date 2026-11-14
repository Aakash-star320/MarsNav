// Client for the science-objective endpoints: which objectives the backend can really analyse, whether NASA's catalog
// has data for an objective it cannot, and how much data this session has read.
import type { BoundingBox } from '../types/contracts';
import { API_BASE } from './analysis';

export interface ObjectiveInfo {
  id: string; label: string; description: string; keywords: string[]; data_used: string[]; limitation: string; kind: 'spectral' | 'terrain';
}
export interface ObjectiveCoverage {
  instrument: string; product_type: string; label: string; measures: string; covered_percent: number | null; product_count: number;
  example_product_ids: string[]; analyzable: boolean; note: string;
}
export interface ObjectiveCheck {
  objective: string; matched_objective_id: string | null; supported: boolean; message: string; coverage: ObjectiveCoverage[]; warnings: string[];
}
export interface DataBudget { per_analysis_cap_bytes: number; session_cap_bytes: number; session_used_bytes: number; analyses_counted: number }

/** Used when the backend cannot be reached: the one objective the analyzer has always supported. */
export const FALLBACK_OBJECTIVES: ObjectiveInfo[] = [{
  id: 'hydrated_minerals', label: 'Hydrated minerals', kind: 'spectral',
  description: 'Sites whose CRISM spectral summary parameters suggest hydrated hydroxylated minerals.',
  keywords: ['hydrated', 'mineral', 'clay', 'phyllosilicate', 'smectite'],
  data_used: ['CRISM MTRDR summary parameters'],
  limitation: 'A heuristic screen of summary parameters, not an identified mineral. Missing coverage is not evidence of absence.',
}];

let cache: ObjectiveInfo[] | null = null;
export const resetObjectivesCache = () => { cache = null; };

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

/** The objectives the backend supports (cached for the session); the built-in list when it cannot be reached. */
export async function fetchObjectives(): Promise<ObjectiveInfo[]> {
  if (cache) return cache;
  try {
    const list = await get<ObjectiveInfo[]>('/objectives');
    if (Array.isArray(list) && list.length) { cache = list; return list; }
  } catch { /* fall through to the built-in list; not cached, so a later call can try again */ }
  return FALLBACK_OBJECTIVES;
}

export async function checkObjective(objective: string, bounds: BoundingBox): Promise<ObjectiveCheck> {
  const res = await fetch(`${API_BASE}/objectives/check`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ objective, bounds }) });
  if (!res.ok) throw new Error(`The objective check answered ${res.status}.`);
  return res.json() as Promise<ObjectiveCheck>;
}

export const fetchDataBudget = () => get<DataBudget>('/data-budget');

/** The objective a piece of text names: id, label or keyword contained in the text, case-insensitive; the longest match wins. */
export function matchObjective(text: string, objectives: ObjectiveInfo[]): ObjectiveInfo | null {
  const t = text.toLowerCase();
  let best: { o: ObjectiveInfo; len: number } | null = null;
  for (const o of objectives) {
    const terms = [o.id, o.id.replace(/_/g, ' '), o.label, ...o.keywords].map((x) => x.toLowerCase().trim()).filter(Boolean);
    for (const term of terms) if (t.includes(term) && (!best || term.length > best.len)) best = { o, len: term.length };
  }
  return best?.o ?? null;
}

export const objectiveLabel = (id: string, objectives: ObjectiveInfo[]) => objectives.find((o) => o.id === id)?.label ?? id;

export const fmtMB = (bytes: number) => (bytes / 1048576).toFixed(bytes < 10 * 1048576 ? 1 : 0);

/** One catalog-coverage line for the chat, for example "THEMIS: 92% covered · not analysable yet". */
export const coverageLine = (c: ObjectiveCoverage) =>
  `${c.label}: ${c.covered_percent == null ? 'coverage unknown' : `${Math.round(c.covered_percent)}% covered`} · ${c.analyzable ? 'analysable' : 'not analysable yet'}`;
