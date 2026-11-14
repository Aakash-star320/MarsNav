import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { fmtMB } from '../../api/objectives';
import { useStore } from '../../store/dashboardStore';
import type { DataState, Mode, Pick } from '../../types/ui';
import { fmtCoord, KM_PER_PX, lonLatToPx } from '../../utils/geo';
import { LAYERS, realLabel } from '../../utils/layers';

const MODES: [Mode, string, string][] = [
  ['analyze', 'Analyze Region', 'Study an area. No destination needed.'],
  ['route', 'Plan Route', 'Start to destination, compare routes.'],
  ['mission', 'Plan Scientific Mission', 'Visit several science sites within your oxygen budget.'],
];
const PRESETS = [['short', 'Shortest distance'], ['safe', 'Safest terrain'], ['bal', 'Balanced']];
const PRIMARY: Record<Mode, [string, 'analyze' | 'generate' | 'plan']> = {
  analyze: ['Analyze Region', 'analyze'], route: ['Generate Routes', 'generate'], mission: ['Plan Mission', 'plan'],
};
const CATS: [keyof DataState['cats'], string][] = [
  ['elev', 'Elevation'], ['slope', 'Slope'], ['rough', 'Roughness'], ['haz', 'Potential hazards'], ['spec', 'Mineral / spectral'],
];

function LocRow({ k, label }: { k: 'start' | 'dest' | 'base'; label: string }) {
  const value = useStore((s) => s[k]);
  const setPick = useStore((s) => s.setPick);
  return (
    <div className="lr"><span>{label}</span><b>{fmtCoord(value)}</b><button onClick={() => setPick(k as Pick)}>Set on map</button></div>
  );
}

function NumField({ k, label, min, step }: { k: 'oxy' | 'res' | 'exam' | 'maxSites' | 'maxd'; label: string; min?: number; step?: number }) {
  const v = useStore((s) => s[k]);
  const setField = useStore((s) => s.setField);
  return (
    <label>{label}
      <input type="number" value={v} min={min} step={step} onChange={(e) => setField(k, e.target.value === '' ? 0 : Number(e.target.value))} />
    </label>
  );
}

function SlopeField({ label }: { label: string }) {
  const slope = useStore((s) => s.slope);
  const setField = useStore((s) => s.setField);
  return (
    <label>{label}: <b>{slope}°</b>
      <input type="range" min={5} max={30} value={slope} onChange={(e) => setField('slope', Number(e.target.value))} />
    </label>
  );
}

/** Oxygen duration and maximum slope are always visible: they are the most important constraints. */
function KeyConstraints() {
  return (
    <div className="key"><NumField k="oxy" label="Oxygen duration available (hours)" min={0.5} step={0.5} /><SlopeField label="Maximum slope" /></div>
  );
}

function Advanced({ children }: { children: ReactNode }) {
  const adv = useStore((s) => s.adv);
  const setField = useStore((s) => s.setField);
  return (
    <details open={adv} onToggle={(e) => setField('adv', (e.currentTarget as HTMLDetailsElement).open)}>
      <summary>Advanced settings</summary>{children}
    </details>
  );
}

function PresetSelect() {
  const preset = useStore((s) => s.preset);
  const setField = useStore((s) => s.setField);
  return (
    <label>Route preference
      <select value={preset} onChange={(e) => setField('preset', e.target.value as DataState['preset'])}>
        {PRESETS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
      </select>
    </label>
  );
}

function Layers() {
  const { layers, lyOpen, setField, toggleLayer, setOpacity, real } = useStore();
  const on = Object.values(layers).filter((l) => l.on).length;
  return (
    <details open={lyOpen} onToggle={(e) => setField('lyOpen', (e.currentTarget as HTMLDetailsElement).open)}>
      <summary>Map layers ({on} on)</summary>
      {LAYERS.map((base) => { const l = realLabel(base, real); return (
        <div className="ly" key={l.id}>
          <label><input type="checkbox" checked={layers[l.id].on} disabled={l.na} onChange={() => toggleLayer(l.id)} /> {l.n}</label>
          <small>{l.s}{l.r ? ' · ' + l.r : ''}</small>
          {!l.na && <input type="range" min={10} max={100} value={Math.round(layers[l.id].op * 100)} aria-label={`${l.n} opacity`} onChange={(e) => setOpacity(l.id, Number(e.target.value) / 100)} />}
        </div>
      ); })}
    </details>
  );
}

/** How much data this session has read from the NASA/USGS sources, against the cap; hidden when the backend does not say. */
function DataUsed() {
  const b = useStore((s) => s.dataBudget);
  if (!b) return null;
  return <p className="nt" data-testid="data-used">Data read this session: {fmtMB(b.session_used_bytes)} MB of {fmtMB(b.session_cap_bytes)} MB.</p>;
}

export default function SetupPanel() {
  const s = useStore();
  const { loadObjectives, refreshDataBudget } = s;
  useEffect(() => { loadObjectives(); refreshDataBudget(); }, [loadObjectives, refreshDataBudget]);
  const { mode, pan, togglePanel } = s;
  if (!pan.L) {
    return <aside id="L" className="col"><button className="rail" onClick={() => togglePanel('L')} title="Show setup panel">▶ Setup</button></aside>;
  }
  const [primaryLabel, primaryAction] = PRIMARY[mode];
  return (
    <aside id="L">
      <div className="ph"><b>Mission setup</b><button onClick={() => togglePanel('L')} title="Hide setup panel" aria-label="Hide setup panel">◀ Hide</button></div>
      <div className="pb">
        <h2>1 · Choose what to do</h2>
        {MODES.map(([v, t, d]) => (
          <button key={v} className={'mb' + (mode === v ? ' on' : '')} onClick={() => s.setMode(v)}><b>{t}</b>{mode === v && <small>{d}</small>}</button>
        ))}
        <h2>2 · Set up</h2>

        {mode === 'analyze' && (
          <>
            <p className="nt">Drag a rectangle on the map, or use the visible map.</p>
            <div className="lr"><span>Region</span><b>{s.region ? <>{(s.region.w * KM_PER_PX).toFixed(1)} × {(s.region.h * KM_PER_PX).toFixed(1)} km<br />{fmtCoord(s.region)}</> : 'none selected'}</b></div>
            <button onClick={s.useVisibleMap}>Use visible map</button>
            <h2>Analyze</h2>
            {CATS.map(([k, t]) => <label key={k}><input type="checkbox" checked={s.cats[k]} onChange={() => s.toggleCat(k)} /> {t}</label>)}
            <Advanced><SlopeField label="Hazard slope threshold" /></Advanced>
          </>
        )}

        {mode === 'route' && (
          <>
            <LocRow k="start" label="Start" /><LocRow k="dest" label="Destination" /><LocRow k="base" label="Base" />
            <button className="inline" title="Sets Start 18.3700 N, 77.4350 E and Destination 18.4100 N, 77.4600 E in Jezero crater, then plans the route. Analyse that area first for routes on real terrain." onClick={() => {
              const a = lonLatToPx({ latitude_deg: 18.37, longitude_deg_east: 77.435 }), b = lonLatToPx({ latitude_deg: 18.41, longitude_deg_east: 77.46 });
              s.setField('start', { ...a });
              s.setField('dest', { ...b });
              s.setField('focusZoom', 13.5);
              s.setField('focus', { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });   // zoom the map onto the route
              setTimeout(() => s.setField('focus', null), 1200);
              s.setField('ret', false);
              s.generate();
            }}>Try demo route (Jezero)</button>
            <div className="lr"><span>Waypoints</span><b>{s.wps.length} added</b><button onClick={() => s.setPick('wp')}>Add</button><button onClick={s.clearWps}>Clear</button></div>
            <PresetSelect />
            <label><input type="checkbox" checked={s.ret} onChange={(e) => s.setField('ret', e.target.checked)} /> Return to base</label>
            <KeyConstraints />
            <Advanced><NumField k="res" label="Emergency reserve (minutes)" /><NumField k="maxd" label="Maximum distance (km)" /></Advanced>
          </>
        )}

        {mode === 'mission' && (
          <>
            <LocRow k="base" label="Base" />
            <label>Scientific objective
              <select value={s.obj} onChange={(e) => s.setField('obj', e.target.value)}>
                {s.objectives.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
              </select>
            </label>
            <p className="nt" data-testid="objective-note">{s.objectives.find((o) => o.id === s.obj)?.limitation}</p>
            <KeyConstraints />
            <NumField k="exam" label="Examination time per site (minutes)" />
            <NumField k="maxSites" label="Maximum number of sites" min={1} />
            <PresetSelect />
            <p className="nt">Return to base: required.</p>
            <Advanced><NumField k="res" label="Emergency reserve (minutes)" /><NumField k="maxd" label="Maximum distance per leg (km)" /></Advanced>
          </>
        )}
        <Layers />
        <DataUsed />
      </div>
      <div className="pf">
        {s.stale && <p className="nt wn" style={{ margin: '0 0 6px' }}>Settings changed. Press {primaryLabel} to update results.</p>}
        {s.err && <div className="er"><b>Problem:</b> {s.err}<br /><button style={{ marginTop: 5 }} onClick={s.dismissError}>Dismiss</button></div>}
        <div className="btns">
          <button className="pri" disabled={!!s.job} onClick={s[primaryAction]}>{primaryLabel}</button>
          <button onClick={s.reset} title="Clear selections and results">Reset</button>
        </div>
      </div>
    </aside>
  );
}
