import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from './dashboardStore';
import { modelLabel, toChatMessage } from '../api/assistant';
import type { AssistantResponse } from '../types/contracts';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const TID = 'b0a1c2d3-0000-4000-8000-000000000001';
const ANSWER: AssistantResponse = {
  message: 'The area is smooth and one candidate met the rule.',
  tool_calls: [
    { id: '1', name: 'analysis_result', arguments: {}, status: 'completed', result: { statistics: { area_km2: 160, valid_percent: 100, elevation_min_m: -2668, elevation_max_m: -2422, slope_mean_deg: 0.9, slope_max_deg: 4.8, slope_limit_deg: 20, slope_exceedance_fraction: 0 } } },
    { id: '2', name: 'target_lookup', arguments: {}, status: 'completed', result: { count: 1, targets: [{ id: TID, title: 'Hydrated candidate', relevance_score: 0.43, confidence: 'low', location: { latitude_deg: 18.45, longitude_deg_east: 77.45 }, evidence: [{ statement: 'CRISM obs: mean D2300 = 0.0114' }] }] } },
    { id: '3', name: 'route_create', arguments: {}, status: 'rejected', error_message: 'not available' },
  ],
  citations: [], actions: [{ type: 'focus_target', payload: { target_id: TID } }, { type: 'focus_roi', payload: { bounds: { west_deg_east: 77.4, south_deg: 18.4, east_deg_east: 77.5, north_deg: 18.5 } } }],
  warnings: ['Coarse 463 m data: broad planning only.'],
};

beforeEach(() => {
  useStore.getState().reset();
  useStore.setState({ online: true, job: null, err: '', chat: [], pendingQ: null, assistantMode: 'gemma', assistantModel: 'test-model' });
});
afterEach(() => vi.restoreAllMocks());

describe('the header names the model that really answers', () => {
  it('Gemma, Gemini and unknown models are labelled as what they are', () => {
    expect(modelLabel('gemma-4-26b-a4b-it')).toBe('Gemma · gemma-4-26b-a4b-it');
    expect(modelLabel('gemini-3.5-flash')).toBe('Gemini · gemini-3.5-flash');
    expect(modelLabel('some-other-model')).toBe('Model · some-other-model');
    expect(modelLabel(null)).toBe('Hosted model');
  });
});

describe('assistant answers become chat messages', () => {
  it('shows tool steps, a result card with candidates, and map actions taken from the tool results', () => {
    const m = toChatMessage(ANSWER, [{ id: TID, cat: 'x', x: 120, y: 80, score: 43, conf: 'Low', label: 'C-01' }]);
    expect(m.r).toBe(ANSWER.message);
    expect(m.steps).toEqual(['Read the analysis summary', 'Looked up candidates', 'Routing (not allowed)']);
    expect(m.card?.stats[0]).toEqual(['Area', '160 km²']);
    expect(m.card?.targets[0]).toMatchObject({ label: 'C-01', score: 43, conf: 'low', at: { x: 120, y: 80 } });
    expect(m.card?.warnings).toEqual(ANSWER.warnings);
    expect(m.actions?.map((a) => a.label)).toEqual(['Show C-01', 'Show region on map', 'Open full details']);
  });

  it('without result data it is plain text, and warnings become a note', () => {
    const m = toChatMessage({ message: 'Hello', tool_calls: [], citations: [], actions: [], warnings: ['The language model was unavailable (timeout).'] }, []);
    expect(m.card).toBeUndefined();
    expect(m.note).toContain('unavailable');
  });
});

describe('chat routing between local actions and the assistant service', () => {
  it('in model mode a question goes to the backend with the current analysis and area, with a pending state in between', async () => {
    let sent: Record<string, unknown> = {};
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input).endsWith('/assistant/messages')) { sent = JSON.parse(String(init?.body)); return reply(ANSWER); }
      return reply({});
    });
    useStore.setState({ region: { x: 100, y: 100, w: 200, h: 100 }, real: { id: 'a1' } as never });
    useStore.getState().sendChat('How steep is this area?');
    expect(useStore.getState().pendingQ).toBe('How steep is this area?');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1));
    const s = useStore.getState();
    expect(s.pendingQ).toBeNull();
    expect(s.chat[0].u).toBe('How steep is this area?');
    expect(s.chat[0].card?.stats.length).toBeGreaterThan(0);
    expect(sent.analysis_id).toBe('a1');
    expect(sent.selected_area).toMatchObject({ west_deg_east: expect.any(Number) });
    expect(sent.message).toBe('How steep is this area?');
  });

  it('a command still runs the checked UI action locally and never calls the assistant service', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ id: 'a2', stage: 'queued', progress_percent: 0, message: 'q', warnings: [] }, 202));
    useStore.setState({ region: { x: 100, y: 100, w: 200, h: 100 } });
    useStore.getState().sendChat('Analyze this region');
    expect(useStore.getState().chat[0].steps).toContain('Started Analyze Region');
    expect(fetchSpy.mock.calls.every(([u]) => !String(u).includes('/assistant/messages'))).toBe(true);
    useStore.getState().cancelJob();             // the analysis it started must not outlive the test
  });

  it('an unreachable service is reported honestly and nothing is made up', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('failed to fetch'));
    useStore.getState().sendChat('What are the data sources?');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1));
    expect(useStore.getState().chat[0]).toMatchObject({ err: true });
    expect(useStore.getState().chat[0].r).toMatch(/could not reach the assistant service/);
    expect(useStore.getState().pendingQ).toBeNull();
  });

  it('in rule-based mode an unrecognised message is still answered by the service (it states its own limits)', async () => {
    useStore.setState({ assistantMode: 'rule_based' });
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ message: 'I can start a terrain analysis for an area.', tool_calls: [], citations: [], actions: [], warnings: [] }));
    useStore.getState().sendChat('blah blah');
    await vi.waitFor(() => expect(useStore.getState().chat).toHaveLength(1));
    expect(useStore.getState().chat[0].r).toContain('terrain analysis');
  });

  it('refuses to call anything while offline', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    useStore.setState({ online: false });
    useStore.getState().sendChat('How steep is it?');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(useStore.getState().chat[0].err).toBe(true);
  });

  it('reads the active mode from the backend, and treats an unreachable backend as rule-based', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ mode: 'gemma', model: 'm1' }));
    useStore.setState({ assistantMode: null, assistantModel: null });
    useStore.getState().refreshAssistant();
    await vi.waitFor(() => expect(useStore.getState().assistantMode).toBe('gemma'));
    expect(useStore.getState().assistantModel).toBe('m1');
    vi.restoreAllMocks();
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('down'));
    useStore.getState().refreshAssistant();
    await vi.waitFor(() => expect(useStore.getState().assistantMode).toBe('rule_based'));
  });
});
