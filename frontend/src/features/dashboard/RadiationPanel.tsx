import { MARS_SURFACE_RADIATION as R, doseForHours, fmtDose, ratePerHour } from '../../utils/radiation';

/**
 * Typical surface radiation, from published Curiosity measurements. It is a stored figure, not live data and not a
 * forecast: it does not know about solar storms, the solar cycle or this area's altitude, and says so.
 */
export default function RadiationPanel({ hours, meanElevationM }: { hours?: number | null; meanElevationM?: number | null }) {
  const hasPlan = hours != null && Number.isFinite(hours) && hours > 0;
  const elev = meanElevationM != null && Number.isFinite(meanElevationM) ? Math.round(meanElevationM) : null;
  return (
    <div className="rad" data-testid="radiation-panel">
      <h2>Radiation <span className="p w">typical value, not a forecast</span></h2>
      <div className="cd">
        <div className="g">
          <span style={{ gridColumn: '1 / -1' }}>Surface rate <b>about {R.doseEquivalentMSvPerDay} mSv per day</b> ({fmtDose(ratePerHour())} per hour)</span>
          {hasPlan && <span style={{ gridColumn: '1 / -1' }}>This plan, {hours.toFixed(1)} h outside <b>about {fmtDose(doseForHours(hours))}</b></span>}
        </div>
        <p>
          Measured by the {R.instrument} in {R.site}, {R.period}. It counts the steady cosmic-ray background only.
          Sudden solar storms, the 11-year solar cycle and altitude all change the real dose, and no live Mars space-weather feed is connected.
          {elev != null && <> This area averages {elev.toLocaleString('en-US')} m; the measurement was made at about {R.siteElevationM.toLocaleString('en-US')} m.</>}
        </p>
        <details><summary>Where the numbers come from</summary>
          <p className="nt">Dose equivalent (how biologically significant the exposure is): {R.doseEquivalentMSvPerDay} mSv per day, as reported by the mission team.
            Absorbed dose (energy per kilogram): {R.absorbedMGyPerDay} ± {R.absorbedUncertaintyMGyPerDay} mGy per day.
            On the journey to Mars the rate was higher, about {R.transitMSvPerDay} mSv per day. The dose for your plan is simple arithmetic: rate × hours ÷ 24.</p>
          <p className="nt">Sources: <a href={R.paperUrl} target="_blank" rel="noreferrer">Hassler et al. 2014 (NASA NTRS)</a> · <a href={R.paperDoi} target="_blank" rel="noreferrer">Science DOI</a> · <a href={R.releaseUrl} target="_blank" rel="noreferrer">SwRI release</a></p>
        </details>
      </div>
    </div>
  );
}
