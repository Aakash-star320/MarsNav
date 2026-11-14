// Client for the assistant endpoints, and the mapping from a backend answer to a chat message.
//
// The backend answers with a hosted Gemma model when one is configured and with its rule-based assistant
// otherwise. Either way the answer's map actions, citations and warnings come from validated tool results; this
// file only turns them into what the chat panel shows.
import type { AssistantRequest, AssistantResponse, AssistantStatus, BoundingBox } from '../types/contracts';
import type { ChatAction, ChatCard, ChatMsg, Target } from '../types/ui';
import { API_BASE } from './analysis';
import { boundsToRegion } from './mapping';
import { lonLatToPx, regionZoom } from '../utils/geo';

export class AssistantError extends Error {}

/** One id per browser session, so the backend can group the conversation; the analysis comes from `analysis_id`. */
const SESSION_MISSION = crypto.randomUUID();

export async function fetchAssistantStatus(): Promise<AssistantStatus> {
  const res = await fetch(`${API_BASE}/assistant/status`);
  if (!res.ok) throw new AssistantError(`status ${res.status}`);
  return res.json() as Promise<AssistantStatus>;
}

export async function askAssistant(message: string, analysisId?: string, area?: BoundingBox): Promise<AssistantResponse> {
  const body: AssistantRequest = { mission_id: SESSION_MISSION, message, ...(analysisId ? { analysis_id: analysisId } : {}), ...(area ? { selected_area: area } : {}) };
  const res = await fetch(`${API_BASE}/assistant/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) throw new AssistantError(`The assistant service answered ${res.status}.`);
  return res.json() as Promise<AssistantResponse>;
}

const STEP_LABEL: Record<string, string> = {
  analysis_status: 'Checked analysis status', analysis_result: 'Read the analysis summary', target_lookup: 'Looked up candidates',
  dataset_status: 'Checked the data sources', analysis_start: 'Started an analysis', route_create: 'Routing', route_replan: 'Routing', navigation_guide: 'Navigation',
};
const num = (v: unknown, d = 0) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : 'n/a');

/** Turns a backend answer into a chat message. `targets` are the dashboard's own targets, so labels and map positions match. */
export function toChatMessage(resp: AssistantResponse, targets: Target[]): Omit<ChatMsg, 'u'> {
  const steps = resp.tool_calls.map((c) => (STEP_LABEL[c.name] ?? c.name) + (c.status === 'completed' ? '' : c.status === 'rejected' ? ' (not allowed)' : ' (failed)'));
  const done = (name: string) => resp.tool_calls.find((c) => c.name === name && c.status === 'completed')?.result as Record<string, any> | undefined;
  const result = done('analysis_result'), lookup = done('target_lookup');
  let card: ChatCard | undefined;
  if (result?.statistics || lookup?.targets) {
    const s = result?.statistics as Record<string, unknown> | undefined;
    card = {
      stats: s ? [
        ['Area', `${num(s.area_km2)} km²`], ['Valid data', `${num(s.valid_percent)}%`],
        ['Elevation', `${num(s.elevation_min_m)} to ${num(s.elevation_max_m)} m`], ['Mean slope', `${num(s.slope_mean_deg, 1)}°`],
        ['Max slope', `${num(s.slope_max_deg, 1)}°`], [`Steeper than ${num(s.slope_limit_deg)}°`, `${num(100 * Number(s.slope_exceedance_fraction ?? 0), 1)}% of cells`],
      ] : [],
      targets: ((lookup?.targets ?? []) as Record<string, any>[]).map((t) => {
        const own = targets.find((x) => x.id === t.id), p = lonLatToPx(t.location);
        return { id: t.id as string, label: own?.label ?? (t.title as string), score: Math.round(100 * Number(t.relevance_score ?? 0)), conf: String(t.confidence ?? 'unknown'),
                 evidence: (t.evidence?.[0]?.statement as string | undefined), at: own ? { x: own.x, y: own.y } : { x: Math.round(p.x), y: Math.round(p.y) } };
      }),
      warnings: resp.warnings,
    };
  }
  const actions: ChatAction[] = [];
  for (const a of resp.actions) {
    if (a.type === 'focus_target') {
      const own = targets.find((t) => t.id === a.payload.target_id);
      if (own) actions.push({ label: `Show ${own.label ?? own.id}`, at: { x: own.x, y: own.y }, id: own.id });
    } else if (a.type === 'focus_roi' && a.payload.bounds) {
      const r = boundsToRegion(a.payload.bounds as BoundingBox);
      actions.push({ label: 'Show region on map', at: { x: r.x + r.w / 2, y: r.y + r.h / 2 }, zoom: regionZoom(r) });
    }
  }
  if (result) actions.push({ label: 'Open full details', open: 'results' });
  return { r: resp.message, steps, ...(card ? { card } : {}), ...(actions.length ? { actions } : {}), ...(!card && resp.warnings.length ? { note: resp.warnings.join(' ') } : {}) };
}
