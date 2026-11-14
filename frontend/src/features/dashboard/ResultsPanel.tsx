import { useStore } from '../../store/dashboardStore';
import { budgetOf, combined } from '../../utils/derive';
import { coarseShare, fmtCoord, fmtDuration } from '../../utils/geo';
import BudgetBar from './BudgetBar';

function AnalyzeSummary() {
  const { summary: s, cats, slope } = useStore();
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
            {cats.rough && <span>Roughness <b>needs backend</b></span>}
            {cats.therm && <span>Thermal <b>coarse</b></span>}
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
              <span>Coarse data <b>{(coarseShare(o, region, base) * 100).toFixed(0)}%</b></span>
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
            <p>Score is a ranking value, not a probability.</p>
          </div>
          {m.ex.length > 0 && <p className="nt"><b>Excluded:</b> {m.ex.map((e) => `${e.t.id} (${e.r})`).join('; ')}</p>}
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
    return <aside id="R" className="col"><button className="rail" onClick={() => togglePanel('R')} title="Show results panel">◀ Results{hasRes ? ' ●' : ''}</button></aside>;
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

        <h2>Science targets</h2>
        {targets.length ? targets.map((t) => (
          <div key={t.id} className={'cd' + (selT === t.id ? ' on' : '')} style={{ ['--c' as string]: '#c0653a' }}>
            <h3><span>{t.id} · {t.cat}</span><span>{t.score}</span></h3>
            <div className="g"><span>Location <b>{fmtCoord(t)}</b></span><span>Confidence <b>{t.conf}</b></span></div>
            <p>Candidate spectral signature, not a confirmed identification. Evidence: demo product. Score is not a probability. Route distance: not calculated.</p>
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
                {x.t && <div className="st" onClick={() => s.gotoStep(i)}><i>◆</i><div>Examine {x.t.id}<span>{s.exam} min · {s.obj} · assumption</span></div></div>}
              </div>
            ))}
            <p className="nt">Steps are planned actions; distances come from the mock route model.</p>
          </>
        )}
      </div>
    </aside>
  );
}
