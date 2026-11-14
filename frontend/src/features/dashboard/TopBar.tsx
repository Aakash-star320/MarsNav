import { useStore } from '../../store/dashboardStore';
import { useMissionStore } from '../../store/missionStore';
import { fmtCoord } from '../../utils/geo';

export default function TopBar() {
  const { region, job, err, summary, routes, mission, online, toggleOnline, toggleAi, real, routeSource } = useStore();
  const view = useMissionStore((m) => m.view), setView = useMissionStore((m) => m.setView);
  const status = job ? `${job.title}…` : err ? 'Error' : summary || routes.length || mission ? 'Results ready' : 'Idle';
  return (
    <header>
      <h1><b>Mars</b>Nav</h1>
      <span className="p">Mission: Jezero Walkabout-01</span>
      <span className="p">Region: {region ? fmtCoord(region) : 'none selected'}</span>
      <span className={'p' + (err ? ' w' : '')}>{status}</span>
      {real ? <span className="p g" title="Elevation, slope and spectral layers come from the backend analysis">{routeSource === 'real' && routes.length ? 'Real terrain and routes · missions simulated' : 'Real terrain analysis · routes simulated'}</span>
        : <span className="p w" title="Run Analyze Region for real terrain">Routes and missions simulated</span>}
      <span className="sp" />
      <button onClick={toggleOnline} style={{ color: online ? '#2dd4d0' : '#e8aa3c' }}>{online ? '● Online' : '○ Offline'}</button>
      <span className="seg" role="group" aria-label="Map view">
        <button className={view === '2d' ? 'on' : ''} onClick={() => setView('2d')}>2D</button>
        <button className={view === '3d' ? 'on' : ''} onClick={() => setView('3d')} title={real ? 'Show the analysed terrain in 3D' : 'Run Analyze Region first to get real terrain'}>3D</button>
      </span>
      <button className="pri inline" onClick={toggleAi}>Ask AI assistant</button>
    </header>
  );
}
