import { useState } from 'react';
import { analyzeAreaOnMap, AnalysisError, fetchMapPackage, type AnalysisJob, type RegionStatistics } from '../api/analysis';
import { useMissionStore } from '../store/missionStore';
import './analysis-panel.css';

type Phase =
  | { kind: 'idle' }
  | { kind: 'running'; job?: AnalysisJob }
  | { kind: 'error'; message: string; code?: string }
  | { kind: 'done'; id: string; stats?: RegionStatistics | null; warnings: string[] };

const n = (v: number | null | undefined, digits = 0, unit = '') => (v == null || !Number.isFinite(v) ? '—' : `${v.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })}${unit}`);

const HINTS: Record<string, string> = {
  area_limit: 'Select a smaller area: the limit is about 50 km across.',
  no_elevation_data: 'No elevation data covers this area.',
  timeout: 'The service is still working. Try again in a moment.',
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ap-stat" title={hint}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

/** Sidebar section for the map view: analyze the selected area with real data and read the results. */
export function AnalysisPanel() {
  const aoi = useMissionStore((s) => s.aoi);
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [limit, setLimit] = useState(12);
  const running = phase.kind === 'running';

  async function run() {
    if (!aoi) return;
    setPhase({ kind: 'running' });
    try {
      const out = await analyzeAreaOnMap(aoi, (job) => setPhase({ kind: 'running', job }), limit);
      setPhase({ kind: 'done', id: out.analysisId, stats: out.statistics, warnings: out.warnings });
    } catch (e) {
      const err = e as AnalysisError;
      setPhase({
        kind: 'error', code: err.code,
        message: e instanceof TypeError ? 'Cannot reach the analysis service. Is the backend running?' : err.message,
      });
    }
  }

  async function recompute(next: number) {
    setLimit(next);
    if (phase.kind !== 'done') return;
    try {
      const pkg = await fetchMapPackage(phase.id, next);
      setPhase({ ...phase, stats: pkg.statistics });
    } catch { /* keep the previous statistics */ }
  }

  const stats = phase.kind === 'done' ? phase.stats : undefined;
  return (
    <section className="analysis-panel" aria-label="Area analysis">
      <div className="section-title">AREA ANALYSIS <span>REAL DATA</span></div>
      <button className="ap-run" onClick={run} disabled={!aoi || running}>
        {running ? 'Analyzing…' : phase.kind === 'done' ? 'Analyze again' : 'Analyze selected area'}
      </button>
      {!aoi && phase.kind !== 'done' && <p className="muted">Choose the Area tool, then click two corners on the map. Keep the area under about 50 km across.</p>}

      {running && (
        <div className="ap-progress" role="status">
          <div className="ap-bar"><i style={{ width: `${phase.job?.progress_percent ?? 3}%` }} /></div>
          <small>{phase.job ? `${phase.job.message} · ${phase.job.progress_percent}%` : 'Starting analysis…'}</small>
        </div>
      )}

      {phase.kind === 'error' && (
        <div className="ap-error" role="alert">
          <b>Analysis failed</b>
          <p>{phase.message}</p>
          {phase.code && HINTS[phase.code] && <small>{HINTS[phase.code]}</small>}
        </div>
      )}

      {phase.kind === 'done' && stats && (
        <>
          <div className="ap-grid">
            <Stat label="Area" value={n(stats.area_km2, 0, ' km²')} />
            <Stat label="Cell size" value={`${n(stats.cell_size_x_m)}×${n(stats.cell_size_y_m)} m`} hint="Source cells are coarse: rocks and small obstacles are not resolved." />
            <Stat label="Elevation" value={`${n(stats.elevation_min_m)} to ${n(stats.elevation_max_m)} m`} hint="Metres. The source file does not state the vertical datum." />
            <Stat label="Relief" value={stats.elevation_max_m != null && stats.elevation_min_m != null ? n(stats.elevation_max_m - stats.elevation_min_m, 0, ' m') : '—'} />
            <Stat label="Mean slope" value={n(stats.slope_mean_deg, 1, '°')} />
            <Stat label="Max slope" value={n(stats.slope_max_deg, 1, '°')} hint={`90th percentile ${n(stats.slope_p90_deg, 1, '°')}, 99th ${n(stats.slope_p99_deg, 1, '°')}`} />
            <Stat label="Valid data" value={n(stats.valid_percent, 1, '%')} hint="Missing cells are excluded, never counted as flat." />
            <Stat label="Targets" value={String(stats.science_candidates)} hint="No science objective is supported yet." />
          </div>
          <div className="ap-limit">
            <label>
              Steep-terrain limit
              <input type="number" min={1} max={45} step={1} value={limit} aria-label="Slope limit in degrees"
                onChange={(e) => { const v = Number(e.target.value); if (v > 0 && v <= 45) void recompute(v); else setLimit(v); }} />°
            </label>
            <p>
              <b>{stats.slope_exceedance_fraction == null ? '—' : n(100 * stats.slope_exceedance_fraction, 1, '%')}</b> of cells are steeper
              <small> ({stats.slope_exceedance_cells.toLocaleString()} of {stats.slope_denominator_cells.toLocaleString()} cells with a defined slope)</small>
            </p>
          </div>
          <div className="ap-sources">
            <b>Sources</b>
            <p>Elevation: USGS MOLA 463 m global DEM. Imagery: Viking MDIM 2.1 colour mosaic (232 m/px) via NASA Mars Trek.</p>
          </div>
        </>
      )}

      {phase.kind === 'done' && phase.warnings.length > 0 && (
        <ul className="ap-warnings">{phase.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}
    </section>
  );
}
