import { useStore } from '../../store/dashboardStore';
import { fmtCoord } from '../../utils/geo';

export default function TopBar() {
  const { region, job, err, summary, routes, mission, online, toggleOnline, toggleAi } = useStore();
  const status = job ? `${job.title}…` : err ? 'Error' : summary || routes.length || mission ? 'Results ready' : 'Idle';
  return (
    <header>
      <h1><b>Mars</b>Nav</h1>
      <span className="p">Mission: Jezero Walkabout-01</span>
      <span className="p">Region: {region ? fmtCoord(region) : 'none selected'}</span>
      <span className={'p' + (err ? ' w' : '')}>{status}</span>
      <span className="p w">Demo data · mock backend</span>
      <span className="sp" />
      <button onClick={toggleOnline} style={{ color: online ? '#2dd4d0' : '#e8aa3c' }}>{online ? '● Online' : '○ Offline'}</button>
      <button disabled title="3D terrain is provided by the map component">2D / 3D</button>
      <button className="pri inline" onClick={toggleAi}>Ask AI assistant</button>
    </header>
  );
}
