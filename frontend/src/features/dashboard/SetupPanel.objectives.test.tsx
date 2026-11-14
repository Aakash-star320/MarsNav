import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import SetupPanel from './SetupPanel';
import { useStore } from '../../store/dashboardStore';
import { FALLBACK_OBJECTIVES, resetObjectivesCache } from '../../api/objectives';
import type { ObjectiveInfo } from '../../api/objectives';

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const LIST: ObjectiveInfo[] = [
  { id: 'hydrated_minerals', label: 'Hydrated minerals', kind: 'spectral', description: 'd', keywords: ['hydrated'], data_used: ['CRISM'], limitation: 'A heuristic screen, not an identified mineral.' },
  { id: 'flat_safe_sites', label: 'Flat safe sites', kind: 'terrain', description: 'd', keywords: ['flat'], data_used: ['MOLA'], limitation: 'Derived from 463 m elevation.' },
  { id: 'high_vantage_points', label: 'High vantage points', kind: 'terrain', description: 'd', keywords: ['vantage'], data_used: ['MOLA'], limitation: 'Derived from 463 m elevation.' },
];
const BUDGET = { per_analysis_cap_bytes: 64 * 1048576, session_cap_bytes: 256 * 1048576, session_used_bytes: 12 * 1048576, analyses_counted: 2 };

function backend(opts: { objectives?: unknown; budget?: unknown | null } = {}) {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith('/objectives')) return opts.objectives === undefined ? reply(LIST) : opts.objectives === null ? Promise.reject(new TypeError('down')) : reply(opts.objectives);
    if (url.endsWith('/data-budget')) return opts.budget === null ? reply({}, 404) : reply(opts.budget ?? BUDGET);
    return reply({});
  });
}

/** The options of the objective select only (the panel has other selects, such as the route preference). */
const objectiveOptions = () => within(screen.getByRole('combobox', { name: /Scientific objective/ })).getAllByRole('option');

beforeEach(() => {
  resetObjectivesCache();
  useStore.getState().reset();
  useStore.setState({ mode: 'mission', objectives: FALLBACK_OBJECTIVES, obj: 'flat_safe_sites', dataBudget: null, pan: { L: true, R: false, B: false } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('the scientific objective select', () => {
  it('lists only what the backend can analyse, and shows the selected objective\'s limit', async () => {
    backend();
    render(<SetupPanel />);
    await waitFor(() => expect(objectiveOptions().map((o) => o.textContent)).toEqual(['Hydrated minerals', 'Flat safe sites', 'High vantage points']));
    expect(screen.queryByText('Thermal properties')).toBeNull();                 // the old fixed names that did nothing are gone
    expect(screen.queryByText('Interesting terrain')).toBeNull();
    expect(screen.getByTestId('objective-note').textContent).toBe('Derived from 463 m elevation.');
    expect((screen.getByRole('combobox', { name: /Scientific objective/ }) as HTMLSelectElement).value).toBe('flat_safe_sites');
  });

  it('choosing another objective keeps its id in the store', async () => {
    backend();
    render(<SetupPanel />);
    await waitFor(() => expect(objectiveOptions()).toHaveLength(3));
    const select = screen.getByRole('combobox', { name: /Scientific objective/ }) as HTMLSelectElement;
    select.value = 'high_vantage_points';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await waitFor(() => expect(useStore.getState().obj).toBe('high_vantage_points'));
  });

  it('with the backend down only the hydrated-minerals objective is offered', async () => {
    useStore.setState({ obj: 'hydrated_minerals' });
    backend({ objectives: null });
    render(<SetupPanel />);
    await waitFor(() => expect(objectiveOptions().map((o) => o.textContent)).toEqual(['Hydrated minerals']));
  });

  it('no simulated thermal or coverage layer is offered', async () => {
    backend();
    useStore.setState({ lyOpen: true });
    render(<SetupPanel />);
    await waitFor(() => expect(screen.getByText(/Map layers/)).toBeTruthy());
    expect(screen.queryByText('Thermal')).toBeNull();
    expect(screen.queryByText('Data coverage')).toBeNull();
  });
});

describe('the data used line', () => {
  it('shows what this session has read against the cap', async () => {
    backend();
    render(<SetupPanel />);
    await waitFor(() => expect(screen.getByTestId('data-used').textContent).toBe('Data read this session: 12 MB of 256 MB.'));
  });

  it('is hidden when the backend does not report it', async () => {
    backend({ budget: null });
    render(<SetupPanel />);
    await waitFor(() => expect(objectiveOptions()).toHaveLength(3));
    expect(screen.queryByTestId('data-used')).toBeNull();
  });
});
