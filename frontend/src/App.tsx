import { useEffect } from 'react';
import TopBar from './features/dashboard/TopBar';
import SetupPanel from './features/dashboard/SetupPanel';
import MapWorkspace from './features/dashboard/MapWorkspace';
import BottomPanel from './features/dashboard/BottomPanel';
import ResultsPanel from './features/dashboard/ResultsPanel';
import { MarsMap } from './features/mars-map/MarsMap';
import { startStoreBridge } from './store/bridge';

// `?view=map` opens the Mars map (2D / 3D terrain) on the same shared mission state; the default
// view is the planning dashboard.
const showMarsMap = () => new URLSearchParams(window.location.search).get('view') === 'map';

export default function App() {
  useEffect(() => startStoreBridge(), []);
  if (showMarsMap()) return <MarsMap />;
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
      </div>
    </>
  );
}
