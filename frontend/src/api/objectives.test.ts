import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FALLBACK_OBJECTIVES, coverageLine, fetchDataBudget, fetchObjectives, fmtMB, matchObjective, objectiveLabel, resetObjectivesCache } from './objectives';
import type { ObjectiveInfo } from './objectives';
import { journeyRegion, parseJourney, parseOxygenHours } from './journey';
import { KM_PER_PX } from '../utils/geo';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const LIST: ObjectiveInfo[] = [
  { id: 'hydrated_minerals', label: 'Hydrated minerals', kind: 'spectral', description: 'd', keywords: ['hydrated', 'mineral', 'clay'], data_used: ['CRISM'], limitation: 'Heuristic screen.' },
  { id: 'flat_safe_sites', label: 'Flat safe sites', kind: 'terrain', description: 'd', keywords: ['flat', 'safe site', 'landing'], data_used: ['MOLA'], limitation: '463 m elevation.' },
  { id: 'high_vantage_points', label: 'High vantage points', kind: 'terrain', description: 'd', keywords: ['vantage', 'high ground', 'overlook'], data_used: ['MOLA'], limitation: '463 m elevation.' },
];

beforeEach(() => resetObjectivesCache());
afterEach(() => vi.restoreAllMocks());

describe('matchObjective', () => {
  it('finds an objective by id, label or keyword, ignoring case', () => {
    expect(matchObjective('Find CLAY signatures', LIST)?.id).toBe('hydrated_minerals');
    expect(matchObjective('show me flat_safe_sites', LIST)?.id).toBe('flat_safe_sites');
    expect(matchObjective('the HIGH VANTAGE POINTS please', LIST)?.id).toBe('high_vantage_points');
    expect(matchObjective('a good overlook', LIST)?.id).toBe('high_vantage_points');
  });
  it('the longest matching term wins, and nothing matches when nothing is named', () => {
    expect(matchObjective('flat landing area near hydrated rock', LIST)?.id).toBe('hydrated_minerals');   // "hydrated" (8) beats "flat" (4) and "landing" (7)
    expect(matchObjective('boxwork formations', LIST)).toBeNull();
    expect(matchObjective('', LIST)).toBeNull();
  });
  it('helpers: labels fall back to the id, megabytes are readable, coverage lines are plain', () => {
    expect(objectiveLabel('flat_safe_sites', LIST)).toBe('Flat safe sites');
    expect(objectiveLabel('unknown', LIST)).toBe('unknown');
    expect([fmtMB(3.2 * 1048576), fmtMB(64 * 1048576)]).toEqual(['3.2', '64']);
    const c = { instrument: 'THEMIS', product_type: 'x', label: 'THEMIS day IR', measures: 'm', covered_percent: 92.4, product_count: 3, example_product_ids: [], analyzable: false, note: '' };
    expect(coverageLine(c)).toBe('THEMIS day IR: 92% covered · not analysable yet');
    expect(coverageLine({ ...c, covered_percent: null, analyzable: true })).toBe('THEMIS day IR: coverage unknown · analysable');
  });
});

describe('fetching', () => {
  it('objectives come from the backend and are cached for the session', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply(LIST));
    expect((await fetchObjectives()).map((o) => o.id)).toEqual(['hydrated_minerals', 'flat_safe_sites', 'high_vantage_points']);
    await fetchObjectives();
    expect(spy).toHaveBeenCalledTimes(1);
  });
  it('when the backend cannot be reached only the built-in hydrated-minerals objective is offered, and a later call tries again', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('down'));
    expect(await fetchObjectives()).toEqual(FALLBACK_OBJECTIVES);
    expect(FALLBACK_OBJECTIVES.map((o) => o.id)).toEqual(['hydrated_minerals']);
    spy.mockImplementation(() => reply(LIST));
    expect(await fetchObjectives()).toHaveLength(3);
  });
  it('an empty or failing answer also falls back, and the data budget is read as given', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply([]));
    expect(await fetchObjectives()).toEqual(FALLBACK_OBJECTIVES);
    vi.restoreAllMocks();
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({ per_analysis_cap_bytes: 64, session_cap_bytes: 256, session_used_bytes: 8, analyses_counted: 2 }));
    expect(await fetchDataBudget()).toMatchObject({ session_used_bytes: 8, analyses_counted: 2 });
    vi.restoreAllMocks();
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => reply({}, 404));
    await expect(fetchDataBudget()).rejects.toThrow();
  });
});

describe('understanding a science journey', () => {
  it('reads oxygen hours in the ways people write them', () => {
    expect([parseOxygenHours('I have four hours of oxygen'), parseOxygenHours('3.5 h left'), parseOxygenHours('a 6-hour trip'), parseOxygenHours('no number here'), parseOxygenHours('0 hours')]).toEqual([4, 3.5, 6, null, null]);
  });
  it('a supported objective with a mission intent is a journey', () => {
    const j = parseJourney('I have four hours of oxygen; find mineral sites and return to base', LIST);
    expect(j).toMatchObject({ intent: true, oxygenH: 4, statesGoal: false });
    expect(j.objective?.id).toBe('hydrated_minerals');
    expect(parseJourney('plan a mission to the highest vantage points with 3 hours', LIST).objective?.id).toBe('high_vantage_points');
  });
  it('an unsupported goal is flagged so the catalog can be asked, and commands for routes or analyses are left alone', () => {
    expect(parseJourney('plan a mission to study boxwork formations with 6 hours of oxygen', LIST)).toMatchObject({ intent: true, objective: null, statesGoal: true, oxygenH: 6 });
    expect(parseJourney('plan the safest route to the clay site', LIST).intent).toBe(false);
    expect(parseJourney('analyze this region for hydrated minerals', LIST).intent).toBe(false);
    expect(parseJourney('avoid slopes above 10 degrees and find clay', LIST).intent).toBe(false);
    expect(parseJourney('hello there', LIST)).toMatchObject({ intent: false, objective: null, statesGoal: false });
  });
  it('the analysis square around the base grows with the oxygen but stays between 12 and 44 km across', () => {
    const base = { x: 120, y: 360 };
    const small = journeyRegion(base, 4), mid = journeyRegion(base, 10), huge = journeyRegion(base, 40);
    expect([small.w * KM_PER_PX, mid.w * KM_PER_PX, huge.w * KM_PER_PX]).toEqual([12, 20, 44]);
    expect(small.x + small.w / 2).toBe(120);
    expect(small.y + small.h / 2).toBe(360);
  });
});
