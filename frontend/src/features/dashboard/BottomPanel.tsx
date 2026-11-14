import { useRef } from 'react';
import { useStore } from '../../store/missionStore';
import type { Tab } from '../../types/ui';
import { warningsOf } from '../../utils/derive';
import ElevationChart from '../routing/ElevationChart';

const TABS: [Tab, string][] = [['elev', 'Elevation profile'], ['slope', 'Slope profile'], ['warn', 'Warnings'], ['data', 'Data coverage'], ['off', 'Offline data']];
const COLLAPSED = 36;

function DataTab() {
  const rows = [
    ['Optical mosaic', 'HiRISE/CTX-class', 'Imagery', '~1 m', '100%', 'historical', 'cached'],
    ['Elevation model', 'MOLA/HRSC-class', 'Topography', '~20 m (grid)', '100%', 'historical', 'cached'],
    ['Spectral cube', 'CRISM-class', 'Mineral', '~18 m', '62%', 'historical', 'partial'],
    ['Thermal inertia', 'THEMIS-class', 'Thermal', 'coarse', '100%', 'historical', 'not downloaded'],
  ];
  return (
    <>
      <table>
        <thead><tr><th>Product (demo)</th><th>Instrument</th><th>Type</th><th>Resolution</th><th>Coverage</th><th>Date</th><th>Cache</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r[0]}>{r.map((x, i) => <td key={i}>{x}</td>)}</tr>)}</tbody>
      </table>
      <p className="nt">Demo metadata. Real values (product IDs, last checked) must come from the backend. Roughness is unavailable until the backend supplies it. Resampling does not create new measurements.</p>
    </>
  );
}

function OfflineTab() {
  const { pk, addPackage, removePackage } = useStore();
  return (
    <>
      <table>
        <thead><tr><th>Package</th><th>Size</th><th>Status</th><th>Updated</th><th /></tr></thead>
        <tbody>{pk.map((p, i) => <tr key={i}><td>{p.n}</td><td>{p.sz}</td><td>{p.st}</td><td>{p.up}</td><td><button onClick={() => removePackage(i)}>Remove</button></td></tr>)}</tbody>
      </table>
      <button style={{ margin: '6px 0' }} onClick={addPackage}>Prepare mission package for current region</button>
      <table>
        <thead><tr><th>Works offline (with package)</th><th>Needs internet</th></tr></thead>
        <tbody><tr><td>Map browsing of downloaded tiles · Manual route planning · Saved targets and layers</td><td>AI assistant (hosted Gemma) · New dataset discovery and download · Refresh packages</td></tr></tbody>
      </table>
      <p className="nt">Offline support shown here is a demo; verify before claiming it works offline.</p>
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
  const warnCount = warningsOf(s).filter((x) => x.k !== 'info').length;
  const clamp = (h: number) => Math.max(120, Math.min(window.innerHeight * 0.7, h));

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
