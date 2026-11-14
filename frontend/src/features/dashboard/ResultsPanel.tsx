import { useStore } from '../../store/dashboardStore';
import { objectiveLabel } from '../../api/objectives';
import { budgetOf, combined } from '../../utils/derive';
import { coarseShare, fmtCoord, fmtDuration } from '../../utils/geo';
import BudgetBar from './BudgetBar';
import RadiationPanel from './RadiationPanel';

const n = (v: number | null | undefined, d = 0, unit = '') => (v == null || !Number.isFinite(v) ? 'n/a' : v.toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }) + unit);

function RealSummary() {
  const { summary: s, real } = useStore();
  if (!real || !s) return null;
  const st = real.stats;
  return (
    <>
      <h2>Region summary <span className="p g">real data</span></h2>
      <div className="cd">
        <div className="g">
          <span>Size <b>{s.w.toFixed(1)}×{s.h.toFixed(1)} km</b></span><span>Grid <b>{st.cols}×{st.rows} cells</b></span>
          <span>Cell size <b>{n(st.cell_size_x_m)}×{n(st.cell_size_y_m)} m</b></span><span>Valid data <b>{n(st.valid_percent, 1, '%')}</b></span>
          <span style={{ gridColumn: '1 / -1' }}>Elevation <b>{n(st.elevation_min_m)} to {n(st.elevation_max_m)} m</b></span>
          <span>Relief <b>{st.elevation_max_m != null && st.elevation_min_m != null ? n(st.elevation_max_m - st.elevation_min_m, 0, ' m') : 'n/a'}</b></span>
          <span>Mean slope <b>{n(st.slope_mean_deg, 1, '°')}</b></span><span>Max slope <b>{n(st.slope_max_deg, 1, '°')}</b></span>
          <span>Cells &gt; {st.slope_limit_deg}° <b>{st.slope_exceedance_fraction == null ? 'n/a' : n(100 * st.slope_exceedance_fraction, 1, '%')}</b></span>
          <span>Candidates <b>{st.science_candidates}</b></span>
        </div>
        <p>Elevation: USGS MOLA 463 m global DEM; the percentage counts {st.slope_exceedance_cells.toLocaleString()} of {st.slope_denominator_cells.toLocaleString()} cells that have a defined slope. Coarse data supports broad planning only and is not a safety assessment.</p>
      </div>
    </>
  );
}

function AnalyzeSummary() {
  const { summary: s, cats, slope, real } = useStore();
  if (real && s) return <RealSummary />;
  return (
    <>
      <h2>Region summary</h2>
      {s ? (
        <div className="cd">
          <div className="g">
            <span>Size <b>{s.w.toFixed(1)}×{s.h.toFixed(1)} km</b></span><span>Optical <b>100%</b></span>
            {cats.elev && <span>Elevation <b>{s.mn.toFixed(0)} to {s.mx.toFixed(0)} m</b></span>}
            {cats.slope && <span>Mean slope <b>{s.sl.toFixed(1)}°</b></span>}
            {cats.haz && <span>Cells &gt; {slope}° <b>{s.hz.toFixed(0)}%</b></span>}
            {cats.spec && <span>Spectral <b>62% (partial)</b></span>}
            {cats.rough && <span>Roughness <b>not available</b></span>}
          </div>
          <p>Resolution varies by layer, see Data coverage tab. Demo values.</p>
        </div>
      ) : <p className="nt">Nothing analyzed yet. Select a region, then press Analyze Region.</p>}
    </>
  );
}

function RouteCards() {
  const s = useStore();
  const { routes, sel, preset, res, oxy, region, base, selectRoute } = s;
  return (
    <>
      <h2>Route comparison</h2>
      {routes.length ? routes.map((r, i) => {
        const o = r.out, t = o.t + (r.ret ? r.ret.t : 0);
        return (
          <div key={r.k} className={'cd clk' + (i === sel ? ' on' : '')} style={{ ['--c' as string]: r.c }} onClick={() => selectRoute(i)}>
            <h3><span>{r.n}{r.k === preset ? ' ★' : ''}</span><span>{o.d.toFixed(1)} km</span></h3>
            <div className="g">
              <span>Time out <b>{fmtDuration(o.t)}</b></span><span>Max slope <b>{o.mx.toFixed(1)}°</b></span>
              <span>Avg slope <b>{o.av.toFixed(1)}°</b></span><span>Up/down <b>{o.up.toFixed(0)}/{o.dn.toFixed(0)} m</b></span>
              <span>Hazard share <b>{((o.over.length / o.p.length) * 100).toFixed(0)}%</b></span>
              <span>Terrain data <b>{r.src ? '100% (463 m cells)' : `${(coarseShare(o, region, base) * 100).toFixed(0)}%`}</b></span>
              <span>Roughness <b>n/a</b></span><span>Feasible <b>{t + s.res <= oxy * 60 ? 'yes' : 'no'}</b></span>
            </div>
            <p>{r.k === 'short' ? 'Most direct; may cross steeper ground.' : r.k === 'safe' ? 'Longer with lower measured slopes. Not guaranteed safe.' : 'Trade-off between distance and slope.'}</p>
            {i === sel && r.ret && <p><b>Return (calculated separately):</b> {r.ret.d.toFixed(1)} km, {fmtDuration(r.ret.t)}, max slope {r.ret.mx.toFixed(1)}°</p>}
          </div>
        );
      }) : <p className="nt">No routes yet. Set Start and Destination, then press Generate Routes.</p>}
      <span hidden>{res}</span>
    </>
  );
}

function MissionSummary() {
  const s = useStore();
  const m = s.mission, c = combined(s), b = budgetOf(s);
  return (
    <>
      <h2>Mission summary</h2>
      {!m && <p className="nt">No mission yet. Set the base and constraints, then press Plan Mission.</p>}
      {m && !m.feasible && <div className="er">{m.msg}</div>}
      {m && m.feasible && c && b && (
        <>
          <div className="cd on" style={{ ['--c' as string]: '#2dd4d0' }}>
            <div className="g">
              <span>Sites <b>{m.legs.length}</b></span><span>Distance <b>{c.s.d.toFixed(1)} km</b></span>
              <span>Max slope <b>{c.s.mx.toFixed(1)}°</b></span><span>Up/down <b>{c.s.up.toFixed(0)}/{c.s.dn.toFixed(0)} m</b></span>
              <span>Science value <b>{m.legs.reduce((a, l) => a + l.t.score, 0)}</b></span><span>Feasible <b className="ok">yes</b></span>
            </div>
            <BudgetBar b={b} />
            <p>The score ranks the candidates.</p>
          </div>
          {m.ex.length > 0 && <p className="nt"><b>Excluded:</b> {m.ex.map((e) => `${e.t.label ?? e.t.id} (${e.r})`).join('; ')}</p>}
        </>
      )}
    </>
  );
}

export default function ResultsPanel() {
  const s = useStore();
  const { pan, mode, targets, selT, nav, togglePanel } = s;
  const hasRes = !!(s.summary || targets.length || s.routes.length || s.mission);
  if (!pan.R) {
    return <aside id="R" className="col"><button className="rail" onClick={() => togglePanel('R')} title="Show results panel"><span className="rc"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg></span><span className="rl">Results</span>{hasRes && <i className="rdot" title="Results are ready" />}</button></aside>;
  }
  const c = combined(s), b = budgetOf(s);
  return (
    <aside id="R">
      <div className="ph"><b>Results</b><button onClick={() => togglePanel('R')} title="Hide results panel" aria-label="Hide results panel">Hide ▶</button></div>
      <div className="pb">
        {mode === 'analyze' && <AnalyzeSummary />}
        {mode === 'route' && <RouteCards />}
        {mode === 'mission' && <MissionSummary />}

        {c && b && (
          <>
            <h2>Time and oxygen budget</h2>
            {mode === 'route' && <BudgetBar b={b} />}
            <button className="pri" style={{ marginTop: 4 }} disabled={!!nav} onClick={s.navStart}>Start Navigation (simulation)</button>
          </>
        )}

        {(c && b) || s.real
          ? <RadiationPanel hours={c && b ? (b.u - s.res) / 60 : null} meanElevationM={s.real?.stats.elevation_mean_m ?? null} />
          : null}

        <h2>Science targets</h2>
        {targets.length ? targets.map((t) => (
          <div key={t.id} className={'cd' + (selT === t.id ? ' on' : '')} style={{ ['--c' as string]: '#c0653a' }}>
            <h3><span>{t.label ?? t.id} · {t.cat}</span><span>{t.score}</span></h3>
            <div className="g"><span>Location <b>{fmtCoord(t)}</b></span><span>Confidence <b>{t.conf}</b></span></div>
            {t.evidence ? (
              <>
                {t.objective && t.objective !== 'hydrated_minerals'
                  ? <p>Candidate site found in the elevation data by a documented rule. The score ranks the candidates.</p>
                  : <p>Candidate site with a hydrated-mineral spectral signature from CRISM. The score ranks the candidates.</p>}
                <details><summary>Evidence and how it was ranked</summary>
                  {t.evidence.map((e, i) => <p key={i} className="nt">{e}</p>)}
                  {t.rank && <p className="nt">{t.rank}</p>}
                </details>
              </>
            ) : <p>Candidate site. The score ranks the candidates.</p>}
            <div className="row">
              <button onClick={() => s.selectTarget(t.id)}>Focus</button>
              <button onClick={() => s.targetAsDest(t.id)}>Set as destination</button>
              <button onClick={() => s.targetAsWp(t.id)}>Add to itinerary</button>
              <button onClick={() => s.askAboutTarget(t.id)}>Ask AI</button>
            </div>
          </div>
        )) : <p className="nt">No targets yet. Run Analyze Region or Plan Mission to discover candidates.</p>}

        {c && (
          <>
            <h2>Itinerary</h2>
            <div className="st" onClick={() => s.gotoStep(-1)}><i>●</i><div>Depart base<span>Planned</span></div></div>
            {c.sg.map((x, i) => (
              <div key={i}>
                <div className="st" onClick={() => s.gotoStep(i)}>
                  <i>→</i>
                  <div>{x.n}<span>{x.s.d.toFixed(1)} km · {fmtDuration(x.s.t)} · computed{x.s.over.length ? <> · <b className="wn">{x.s.over.length} steep samples</b></> : null}</span></div>
                </div>
                {x.t && <div className="st" onClick={() => s.gotoStep(i)}><i>◆</i><div>Examine {x.t.label ?? x.t.id}<span>{s.exam} min · {objectiveLabel(s.obj, s.objectives)} · assumption</span></div></div>}
              </div>
            ))}
            <p className="nt">Steps are planned actions.</p>
          </>
        )}
      </div>
    </aside>
  );
}
