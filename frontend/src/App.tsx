import TopBar from './features/dashboard/TopBar';
import SetupPanel from './features/dashboard/SetupPanel';
import MapWorkspace from './features/mars-map/MapWorkspace';
import BottomPanel from './features/dashboard/BottomPanel';
import ResultsPanel from './features/dashboard/ResultsPanel';

export default function App() {
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
