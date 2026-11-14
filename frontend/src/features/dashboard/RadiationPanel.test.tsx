import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import RadiationPanel from './RadiationPanel';
import { MARS_SURFACE_RADIATION, doseForHours, fmtDose, ratePerHour } from '../../utils/radiation';

describe('radiation arithmetic', () => {
  it('is the published rate times the hours outside, divided by 24', () => {
    expect(doseForHours(24)).toBeCloseTo(MARS_SURFACE_RADIATION.doseEquivalentMSvPerDay, 9);
    expect(doseForHours(6)).toBeCloseTo(MARS_SURFACE_RADIATION.doseEquivalentMSvPerDay / 4, 9);
    expect(doseForHours(0)).toBe(0);
    expect(doseForHours(-3)).toBe(0);                                   // a negative duration is never a negative dose
    expect(ratePerHour() * 24).toBeCloseTo(MARS_SURFACE_RADIATION.doseEquivalentMSvPerDay, 9);
  });

  it('formats small doses in microsieverts and larger ones in millisieverts', () => {
    expect(fmtDose(0.028)).toBe('28 µSv');
    expect(fmtDose(0.13)).toBe('0.13 mSv');
    expect(fmtDose(1.5)).toBe('1.5 mSv');
    expect(fmtDose(Number.NaN)).toBe('n/a');
  });
});

describe('the radiation panel', () => {
  afterEach(cleanup);

  it('names the source and still lists what it does not cover', () => {
    render(<RadiationPanel hours={4.6} meanElevationM={-2504} />);
    const panel = screen.getByTestId('radiation-panel');
    expect(panel.textContent).toContain('about 0.67 mSv per day');
    expect(panel.textContent).toMatch(/Gale crater/);
    expect(panel.textContent).toMatch(/solar storms/i);
    expect(panel.textContent).toMatch(/no live Mars space-weather feed/i);
    expect(panel.querySelector('a[href*="ntrs.nasa.gov"]')).not.toBeNull();
  });

  it('shows the dose for the plan, and the area elevation next to where it was measured', () => {
    render(<RadiationPanel hours={4.6} meanElevationM={-2504} />);
    const text = screen.getByTestId('radiation-panel').textContent ?? '';
    expect(text).toContain('4.6 h outside');
    expect(text).toContain(fmtDose(doseForHours(4.6)));
    expect(text).toContain('-2,504 m');
    expect(text).toContain('-4,400 m');
  });

  it('without a plan it shows only the rate, and with no elevation it does not invent one', () => {
    render(<RadiationPanel hours={null} meanElevationM={null} />);
    const text = screen.getByTestId('radiation-panel').textContent ?? '';
    expect(text).not.toMatch(/outside/);
    expect(text).not.toMatch(/This area averages/);
    expect(text).toContain('per hour');
  });
});
