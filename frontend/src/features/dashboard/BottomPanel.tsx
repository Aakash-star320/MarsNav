import { useRef, useState } from 'react';
import { useStore } from '../../store/dashboardStore';
import type { Tab } from '../../types/ui';
import { warningsOf } from '../../utils/derive';
import ElevationChart from '../routing/ElevationChart';

const TABS: [Tab, string][] = [['elev', 'Elevation profile'], ['slope', 'Slope profile'], ['warn', 'Warnings'], ['data', 'Data coverage'], ['off', 'Offline data']];
const COLLAPSED = 58;

function DataTab() {
  const real = useStore((st) => st.real);
  const cell = real ? `${Math.round(real.stats.cell_size_x_m)} × ${Math.round(real.stats.cell_size_y_m)} m cells` : '463 m cells';
  const rows = [
    ['Optical imagery', 'Viking MDIM 2.1 colour mosaic (NASA Mars Trek)', 'Context only', '232 m/px', 'Global', 'Used as the base map'],
    ['Elevation, slope, roughness', 'MOLA global DEM (USGS)', 'Topography', cell, real ? '100% of this area' : 'Global', 'Routing and 3D use this'],
    ['Mineral evidence', 'CRISM MTRDR summary parameters (PDS)', 'Spectral screen', '18 to 36 m/px', 'Where CRISM observed', 'Mineral candidates'],
  ];
  return (
    <>
      <table>
        <thead><tr><th>Layer</th><th>Source</th><th>Kind</th><th>Resolution</th><th>Coverage</th><th>Use</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r[0]}>{r.map((x, i) => <td key={i}>{x}</td>)}</tr>)}</tbody>
      </table>
      <p className="nt">These are the NASA and USGS data sources MarsNav reads when you analyse a region.</p>
    </>
  );
}

function OfflineTab() {
  return (
    <>
      <table>
        <thead><tr><th>What is saved on this computer</th><th>What needs the internet</th></tr></thead>
        <tbody><tr>
          <td>Finished analyses (terrain and results) are stored on disk and reused for the same area, even after a restart. Routes and mission plans are kept only while the backend runs.</td>
          <td>Reading new elevation, imagery tiles and CRISM data; the hosted AI model; the NASA catalog check.</td>
        </tr></tbody>
      </table>
      <p className="nt">There is no download manager or offline map package yet.</p>
    </>
  );
}

function WarningsTab() {
  const s = useStore();
  const w = warningsOf(s);
  if (!w.length) return <p className="nt">No warnings. Generate a route or mission to evaluate terrain.</p>;
  return (
    <>
      {w.map((x, i) => (
        <div key={i} className={'wr ' + x.k} onClick={() => s.focusWarning(x.at)}>
          <div>{x.k === 'bad' ? '⛔' : x.k === 'info' ? 'ℹ' : '⚠'}</div>
          <div>{x.t}{x.at && <> <span className="nt">Click to locate on map.</span></>}</div>
        </div>
      ))}
    </>
  );
}

export default function BottomPanel() {
  const s = useStore();
  const { pan, bh, tab, setTab, togglePanel, setPanelHeight } = s;
  const drag = useRef<{ y: number; h: number } | null>(null);
  const open = pan.B;
  const [menu, setMenu] = useState(false);
  const warnCount = warningsOf(s).filter((x) => x.k !== 'info').length;
  const clamp = (h: number) => Math.max(120, Math.min(window.innerHeight * 0.75, h));

  return (
    <div id="bt" style={{ height: open ? bh : COLLAPSED }}>
      <div id="rz" role="separator" aria-orientation="horizontal" tabIndex={0}
        aria-label="Resize analytics panel: drag, or use Up and Down arrow keys. Double-click to collapse or expand."
        title="Drag to resize · double-click to collapse or expand"
        onPointerDown={(e) => {
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
          drag.current = { y: e.clientY, h: open ? bh : COLLAPSED };
          if (!open) { setPanelHeight(Math.max(bh, 200)); s.openPanels(false, true); }
        }}
        onPointerMove={(e) => { if (!drag.current) return; setPanelHeight(clamp(drag.current.h + drag.current.y - e.clientY)); s.openPanels(false, true); }}
        onPointerUp={() => { drag.current = null; }}
        onDoubleClick={() => togglePanel('B')}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
          e.preventDefault(); s.openPanels(false, true); setPanelHeight(clamp(bh + (e.key === 'ArrowUp' ? 30 : -30)));
        }}><i /></div>
      <div id="tb">
        <button className="tabburger" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-label="Choose a panel">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
          {TABS.find(([k]) => k === tab)?.[1]}
        </button>
        {menu && <div className="tabpop">{TABS.map(([k, t]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => { setTab(k); setMenu(false); s.openPanels(false, true); }}>{t}{k === 'warn' && warnCount ? ` (${warnCount})` : ''}</button>)}</div>}
        {TABS.map(([k, t]) => (
          <button key={k} className={'tab' + (tab === k ? ' on' : '')} onClick={() => setTab(k)}>{t}{k === 'warn' && warnCount ? ` (${warnCount})` : ''}</button>
        ))}
        <span className="sp" />
        <span className="nt" style={{ margin: '0 8px' }}>{open ? 'Drag the top edge to resize' : 'Collapsed. Open a tab or drag the top edge up'}</span>
        <button onClick={() => togglePanel('B')}>{open ? '▼ Collapse' : '▲ Expand'}</button>
      </div>
      <div id="bb">
        {(tab === 'elev' || tab === 'slope') && <ElevationChart mode={tab} />}
        {tab === 'warn' && <WarningsTab />}
        {tab === 'data' && <DataTab />}
        {tab === 'off' && <OfflineTab />}
      </div>
    </div>
  );
}
