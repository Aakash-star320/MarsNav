import { MarsMap } from './features/mars-map/MarsMap';
import { AnalysisPanel } from './app/AnalysisPanel';

/** The Mars map with real data: analysis panel in the sidebar, honest wording, no demo fixtures. */
export default function MapView() {
  return (
    <MarsMap
      workspace={{ eyebrow: 'MARS TERRAIN EXPLORER', title: 'Choose an area.', subtitle: 'Real elevation and imagery, analyzed on demand' }}
      viewBar={{ eyebrow: 'MARS · PLANETOCENTRIC · EAST-POSITIVE LONGITUDE', title: 'Surface map' }}
      badge={null}
      caption="Imagery: Viking MDIM 2.1 (232 m/px) · Layers: USGS MOLA 463 m"
      sidebarExtra={<AnalysisPanel />}
      notes={
        <div className="bottom-note">
          <div>
            <span className="eyebrow">DATA INTEGRITY</span>
            <b>Missing coverage stays missing.</b>
            <p>Cells without elevation are transparent and left out of every statistic, never counted as flat ground.</p>
          </div>
          <div>
            <span className="eyebrow">RESOLUTION</span>
            <b>Broad planning, not obstacle detection.</b>
            <p>The elevation model is a 463 m global product. It cannot show rocks, small craters or other hazards, and slope is not a safety assessment.</p>
          </div>
        </div>
      }
    />
  );
}
