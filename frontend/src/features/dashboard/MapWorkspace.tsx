import { lazy, Suspense, useEffect, useState } from 'react';
import { useStore } from '../../store/dashboardStore';
import { useMissionStore } from '../../store/missionStore';
import { combined } from '../../utils/derive';
import { fmtDuration } from '../../utils/geo';
import { LAYERS } from '../../utils/layers';
import MapCanvas from './MapCanvas';

const Terrain3D = lazy(() => import('../mars-map/Terrain3D').then((m) => ({ default: m.Terrain3D })));

const LEGEND: Record<string, string> = {
  opt: 'Real imagery: NASA Mars Trek (Viking, 232 m)', elev: 'Simulated elevation: blue low → white high', slope: 'Simulated slope: green gentle → red steep',
};
const REAL_LEGEND: Record<string, string> = {
  elev: 'Elevation (MOLA): blue low → orange high', slope: 'Slope: green gentle → red steep',
  spec: 'Magenta: strong hydrated-mineral evidence (heuristic, CRISM)',
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
  const { layers, slope, real, routeSource, routes, mode } = useStore();
  const [open, setOpen] = useState(false);
  const realRoutes = routeSource === 'real' && routes.length > 0 && mode === 'route';
  const items = LAYERS.filter((l) => layers[l.id].on).map((l) => (l.id === 'haz' ? `Red cells: slope > ${slope}°` : (real && REAL_LEGEND[l.id]) || LEGEND[l.id])).filter(Boolean);
  const cell = real ? `${Math.round(real.stats.cell_size_y_m)} m cells` : 'simulated layers';
  return (
    <div className="lgdock">
      {open ? (
        <div className="ov lgcard" id="lg">
          <button className="lgx" onClick={() => setOpen(false)} aria-label="Close legend">×</button>
          <b>Legend</b>
          <span className="lgkey">{items.join(' · ') || 'No layers on'}</span>
          <span className="lgwarn">{real ? `Elevation, slope, steep-terrain and spectral layers are real analysis (463 m terrain). ${realRoutes ? 'Routes follow that real terrain; missions are simulated.' : 'Routes and missions are simulated.'}` : 'Routes, targets and terrain layers are simulated.'}</span>
          <span className="lgkey">Solid = outbound · dashed = return · ◆ target · dotted = previous</span>
        </div>
      ) : (
        <button className="ov lgpill" onClick={() => setOpen(true)} aria-label="Open legend"><i className="dot" />Legend</button>
      )}
      {real && <span className="ov lgres" title="Terrain resolution: features smaller than a cell, such as boulders and small craters, cannot be seen">{cell}</span>}
    </div>
  );
}

function JobOverlay() {
  const { job, cancelJob } = useStore();
  if (!job) return null;
  const pct = Math.max(6, Math.min(96, ((job.i + 0.5) / Math.max(1, job.stages.length)) * 100));
  return (
    <div className="ov" id="jb" role="status" aria-live="polite">
      <div className="jspin" aria-hidden="true" />
      <b>{job.title}…</b>
      <div className="jbar"><i style={{ width: `${pct}%` }} /></div>
      <button onClick={cancelJob}>Cancel</button>
    </div>
  );
}

function NavHud() {
  const s = useStore();
  const c = combined(s), n = s.nav, refreshGuide = s.refreshGuide;
  useEffect(() => {
    if (!n || !c) return;
    const p = c.s.p, i = Math.min(n.i, p.length - 1), b = p[Math.min(p.length - 1, i + 8)], a = p[i];
    refreshGuide({ x: a.x, y: a.y }, ((Math.atan2(b.x - a.x, -(b.y - a.y)) * 57.3) + 360) % 360);
  }, [n?.i, s.sel, s.routes]);
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
      {s.guideText && <div className="guide"><small>Routing service</small>{s.guideText}</div>}
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

/** Small bar shown when the chat is tucked away: the last answer in one line, and a way back. */
function ChatBar() {
  const { aiOpen, aiBar, toggleAi } = useStore();
  if (aiOpen || !aiBar) return null;
  return (
    <div id="aibar" role="status">
      <span className="cx-orb sm">✦</span>
      <span className="cx-bar-t">{aiBar}</span>
      <button className="cx-bar-open" onClick={toggleAi}>Open chat</button>
      <button className="cx-x sm" aria-label="Dismiss" onClick={() => useStore.setState({ aiBar: null })}>×</button>
    </div>
  );
}

export default function MapWorkspace() {
  const view = useMissionStore((m) => m.view);
  const hasTerrain = useMissionStore((m) => !!m.dem);
  const { real, job, err, analyzeTerrainView } = useStore();
  const is3d = view === '3d';
  // Entering 3D reads the real elevation for the area on screen (or the selected region) by itself.
  useEffect(() => { if (is3d && !real) analyzeTerrainView(); }, [is3d]);
  return (
    <div id="mw">
      {/* The 2D map stays mounted (hidden) in 3D, so its zoom and position are kept when you come back. */}
      <div className="v2d" style={{ display: is3d ? 'none' : undefined }}>
        <Banner />
        <MapCanvas />
      </div>
      {is3d && (real && hasTerrain ? (
        <Suspense fallback={<div className="ov" id="bn">Loading the 3D terrain…</div>}><div className="v3d"><Terrain3D /></div></Suspense>
      ) : (
        <div className="v3d"><div className="empty3d">
          {!job && <>
          <span>△</span>
          <h2>{job ? 'Reading real terrain…' : err ? '3D terrain could not be loaded' : 'The 3D view needs real terrain'}</h2>
          <p>{job ? 'Reading the real elevation (USGS MOLA) for the area on the map. The 3D surface appears here in a moment.'
            : err ? err : 'Real elevation for this area has not been read yet.'}</p>
          {!job && <button className="pri inline" onClick={analyzeTerrainView}>{err ? 'Try again' : 'Load 3D terrain'}</button>}
          <button onClick={() => useMissionStore.getState().setView('2d')}>Back to 2D map</button>
          </>}
        </div></div>
      ))}
      <Legend />
      <JobOverlay />
      <NavHud />
      <ChatBar />
    </div>
  );
}
