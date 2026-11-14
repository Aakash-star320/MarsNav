import { useStore } from '../../store/dashboardStore';
import { useMissionStore } from '../../store/missionStore';
import { fmtCoord } from '../../utils/geo';

export default function TopBar() {
  const { region, job, err, summary, routes, mission, online, toggleOnline, toggleAi } = useStore();
  const view = useMissionStore((m) => m.view), setView = useMissionStore((m) => m.setView);
  const status = job ? `${job.title}…` : err ? 'Error' : summary || routes.length || mission ? 'Results ready' : 'Idle';
  return (
    <header className="topbar">
      <h1><b>Mars</b>Nav</h1>
      <div className="hchips">
        <span className="p opt" title="Mission">Jezero Walkabout-01</span>
        <span className="p keep mono" title="Centre of the selected region">{region ? fmtCoord(region) : 'No region selected'}</span>
        <span className={'p keep' + (err ? ' w' : '')}>{status}</span>
      </div>
      <div className="hright">
        <button className={'online' + (online ? '' : ' off')} onClick={toggleOnline} title="Switch the app between online and offline behaviour"><i />{online ? 'Online' : 'Offline'}</button>
        <span className="seg" role="group" aria-label="Map view">
          <button className={view === '2d' ? 'on' : ''} onClick={() => setView('2d')}>2D</button>
          <button className={view === '3d' ? 'on' : ''} onClick={() => setView('3d')} title='Show the terrain in 3D'>3D</button>
        </span>
        <button className="pri inline" onClick={toggleAi}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 2l1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2z" fill="currentColor" /></svg>
          Ask AI assistant
        </button>
      </div>
    </header>
  );
}
