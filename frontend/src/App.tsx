import { lazy, Suspense, useEffect } from 'react';
import TopBar from './features/dashboard/TopBar';
import SetupPanel from './features/dashboard/SetupPanel';
import MapWorkspace from './features/dashboard/MapWorkspace';
import BottomPanel from './features/dashboard/BottomPanel';
import ResultsPanel from './features/dashboard/ResultsPanel';
import ChatPanel from './features/dashboard/ChatPanel';
import { startStoreBridge } from './store/bridge';

// The Mars map module ships its own global stylesheet, so it is loaded only for the map view and
// cannot restyle the dashboard.
const MapView = lazy(() => import('./MapView'));

// `?view=map` opens the Mars map (2D / 3D terrain) with real data; the default view is the dashboard.
const showMarsMap = () => new URLSearchParams(window.location.search).get('view') === 'map';

function Dashboard() {
  useEffect(() => startStoreBridge(), []);
  return (
    <>
      <TopBar />
      <div id="main">
        <SetupPanel />
        <div id="cw">
          <MapWorkspace />
          <BottomPanel />
        </div>
        <ResultsPanel />
        <ChatPanel />
      </div>
    </>
  );
}

export default function App() {
  if (showMarsMap()) {
    return (
      <Suspense fallback={<div style={{ padding: 24, color: '#9fb0c0' }}>Loading the Mars map…</div>}>
        <MapView />
      </Suspense>
    );
  }
  return <Dashboard />;
}
