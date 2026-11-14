import { useState } from 'react';
import { analyzeAreaOnMap, AnalysisError } from '../api/analysis';
import { useMissionStore } from '../store/missionStore';

type Status = { kind: 'idle' } | { kind: 'running'; text: string } | { kind: 'done'; warnings: string[] } | { kind: 'error'; text: string };

/** Floating control for the map view: analyzes the selected area with real MOLA data and shows the layers. */
export function AnalyzeAreaControl() {
  const aoi = useMissionStore((s) => s.aoi);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  const running = status.kind === 'running';

  async function run() {
    if (!aoi) return;
    setStatus({ kind: 'running', text: 'Starting analysis' });
    try {
      const warnings = await analyzeAreaOnMap(aoi, (j) => setStatus({ kind: 'running', text: `${j.message} (${j.progress_percent}%)` }));
      setStatus({ kind: 'done', warnings });
    } catch (e) {
      const err = e as AnalysisError;
      setStatus({ kind: 'error', text: err instanceof TypeError ? 'Cannot reach the analysis service. Is the backend running?' : err.message });
    }
  }

  return (
    <div role="region" aria-label="Area analysis" style={{
      position: 'fixed', left: '50%', bottom: 18, transform: 'translateX(-50%)', zIndex: 1000, maxWidth: 'min(640px, 92vw)',
      background: 'rgba(12,18,30,.94)', color: '#e6edf7', border: '1px solid #2a3a55', borderRadius: 10, padding: '10px 14px',
      font: '13px/1.4 system-ui, sans-serif', boxShadow: '0 6px 24px rgba(0,0,0,.45)',
    }}>
      <button onClick={run} disabled={!aoi || running} style={{
        padding: '6px 12px', borderRadius: 6, border: '1px solid #2dd4d0', background: aoi && !running ? '#2dd4d0' : '#233049',
        color: aoi && !running ? '#04202a' : '#8aa0c0', fontWeight: 600, cursor: aoi && !running ? 'pointer' : 'not-allowed',
      }}>
        {running ? 'Analyzing…' : 'Analyze this area (real MOLA data)'}
      </button>
      <span style={{ marginLeft: 10, color: '#9fb0c8' }}>
        {!aoi && 'Choose the Area tool and select two corners first.'}
        {status.kind === 'running' && status.text}
        {status.kind === 'error' && <span style={{ color: '#f47e72' }}>{status.text}</span>}
        {status.kind === 'done' && 'Layers loaded. Switch them on in the Surface layers panel.'}
      </span>
      {status.kind === 'done' && status.warnings.length > 0 && (
        <ul style={{ margin: '6px 0 0 18px', padding: 0, color: '#c9a45c' }}>{status.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}
    </div>
  );
}
