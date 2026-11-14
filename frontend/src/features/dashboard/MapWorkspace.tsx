import { useStore } from '../../store/dashboardStore';
import { combined } from '../../utils/derive';
import { fmtDuration } from '../../utils/geo';
import { LAYERS } from '../../utils/layers';
import MapCanvas from './MapCanvas';

const LEGEND: Record<string, string> = {
  opt: 'Real imagery: NASA Mars Trek (Viking, 232 m)', elev: 'Simulated elevation: blue low → white high', slope: 'Simulated slope: green gentle → red steep',
  therm: 'Thermal (orange)', cov: 'Coverage: teal detailed · amber moderate · grey coarse',
};

function Banner() {
  const s = useStore();
  const { mode, pick, job } = s;
  const P: Record<string, string> = {
    region: 'Drag on the map to select a region', start: 'Click the map to set the Start', dest: 'Click the map to set the Destination',
    base: 'Click the map to set the Base', wp: 'Click the map to add a waypoint', obs: 'Click the map where the obstacle is', cur: 'Click the map to set your simulated position',
  };
  if (pick && P[pick]) return <div className="ov" id="bn"><b>Waiting for you:</b> {P[pick]} <button style={{ padding: '1px 7px' }} onClick={() => s.setPick(null)}>Cancel</button></div>;
  if (job) return <div className="ov" id="bn">Working… see progress</div>;
  let next: string;
  if (mode === 'analyze') next = !s.region ? 'drag on the map to select a region' : !s.summary ? 'press Analyze Region' : 'inspect targets at right, or set one as destination';
  else if (mode === 'route') next = !s.start ? 'set a Start (left panel, Set on map)' : !s.dest ? 'set a Destination' : !s.routes.length ? 'press Generate Routes' : 'compare routes at right, then Start Navigation';
  else next = !s.mission ? 'press Plan Mission' : 'review the mission at right';
  return <div className="ov" id="bn"><b>Next:</b> {next}</div>;
}

function Legend() {
  const { layers, slope } = useStore();
  const items = LAYERS.filter((l) => layers[l.id].on).map((l) => (l.id === 'haz' ? `Red cells: slope > ${slope}°` : LEGEND[l.id])).filter(Boolean);
  return (
    <div className="ov" id="lg"><b>Legend</b> {items.join(' · ') || 'No layers on'}<br />
      <span style={{ color: '#f0b254' }}>Routes, targets and terrain layers are simulated.</span><br />
      <span style={{ color: '#b4c1d8' }}>Solid = outbound · dashed = return · ◆ target · dotted = previous</span>
    </div>
  );
}

function JobOverlay() {
  const { job, cache, cancelJob } = useStore();
  if (!job) return null;
  return (
    <div className="ov" id="jb">
      <b>{job.title}…</b> <span className="p w">simulated job</span>
      {job.stages.map((x, i) => (
        <div key={x} style={{ fontSize: 13, color: i < job.i ? '#2dd4d0' : i === job.i ? '#fff' : '#b4c1d8' }}>
          {i < job.i ? '✓' : i === job.i ? '●' : '○'} {x}{x === 'Download' && cache ? ' (cache reused)' : ''}
        </div>
      ))}
      <div className="bar"><i style={{ width: `${(job.i / job.stages.length) * 100}%`, background: '#2dd4d0' }} /></div>
      <div className="nt">Next: {job.stages[job.i + 1] ?? 'finish'}. Replace with real backend job status.</div>
      <button style={{ marginTop: 6 }} onClick={cancelJob}>Cancel</button>
    </div>
  );
}

function NavHud() {
  const s = useStore();
  const c = combined(s), n = s.nav;
  if (!n || !c) return null;
  const st = c.s, i = Math.min(n.i, st.p.length - 1), j = Math.min(st.p.length - 1, i + 8), a = st.p[i], b = st.p[j];
  const hd = ((Math.atan2(b.x - a.x, -(b.y - a.y)) * 57.3) + 360) % 360, rem = st.d - st.cum[i];
  const sg = c.sg[c.b.filter((x) => x <= i).length - 1], done = i >= st.p.length - 1;
  return (
    <div className="ov" id="hud">
      <b>Navigation (simulation, not real Mars GPS)</b>
      <div className="g" style={{ margin: '5px 0' }}>
        <span>Segment <b>{sg.n}</b></span><span>Remaining <b>{rem.toFixed(1)} km</b></span>
        <span>Time left <b>{fmtDuration((rem / 2) * 60)}</b></span><span>Heading <b>{hd.toFixed(0)}°</b></span>
        <span>Elevation <b>{st.el[i].toFixed(0)} m</b></span><span>Upcoming slope <b>{st.sl[Math.min(i + 3, st.sl.length - 1)].toFixed(1)}°</b></span>
        <span>Oxygen left <b>{fmtDuration(Math.max(0, s.oxy * 60 - st.t * (st.cum[i] / st.d)))}</b></span>
      </div>
      <div style={{ margin: '4px 0' }}><b>{done ? 'Arrived at end of route.' : `Travel ${((st.cum[j] - st.cum[i]) * 1000).toFixed(0)} m at heading ${hd.toFixed(0)}°`}</b></div>
      <div className="hudbtns">
        <button onClick={s.navPause}>{n.paused ? 'Resume' : 'Pause'}</button>
        <button onClick={() => s.navAdvance(5)}>Advance</button>
        <button onClick={() => s.setPick('cur')}>Set position</button>
        <button onClick={() => s.setPick('obs')}>Report obstacle</button>
        <button onClick={s.navEnd}>End</button>
      </div>
    </div>
  );
}

const CHIPS = ['Analyze this region', 'Find the safest route', 'I have four hours of oxygen; find mineral sites and return to base', 'Avoid slopes above 10 degrees', 'Why are hydrated minerals important?'];
const CHIP_LABELS = ['Analyze this region', 'Safest route', '4 h mission', 'Avoid slopes > 10°', 'Why hydrated minerals?'];

function AssistantDrawer() {
  const { aiOpen, toggleAi, chat, aiDraft, setAiDraft, sendChat } = useStore();
  if (!aiOpen) return null;
  return (
    <div className="ov" id="ai">
      <b>AI Mission Assistant</b> <span className="p w">mock · no LLM</span>
      <button style={{ float: 'right', padding: '1px 7px' }} onClick={toggleAi} aria-label="Close assistant">×</button>
      <div className="ms">
        <p className="nt">Ask me to analyze a region, plan a route or plan a mission. I trigger the same verified actions as the buttons.</p>
        {chat.map((m, i) => <div key={i}><p className="u">You: {m.u}</p><p className={m.err ? 'bd' : undefined}>{m.r}{m.note && <> <span className="nt">{m.note}</span></>}</p></div>)}
      </div>
      <div className="chips">{CHIPS.map((c, i) => <button key={c} onClick={() => sendChat(c)}>{CHIP_LABELS[i]}</button>)}</div>
      <input value={aiDraft} placeholder="Type a request and press Enter" aria-label="Message the assistant"
        onChange={(e) => setAiDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') sendChat(aiDraft); }} />
    </div>
  );
}

export default function MapWorkspace() {
  return (
    <div id="mw">
      <Banner />
      <MapCanvas />
      <Legend />
      <JobOverlay />
      <NavHud />
      <AssistantDrawer />
    </div>
  );
}
