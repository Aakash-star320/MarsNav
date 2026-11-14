import { useEffect, useState } from "react";
import { MarsMap } from "./MarsMap";
import { useMissionStore as store } from "../../store/missionStore";
import { applyFixtureResponse, demoDem, loadDemo, mission } from "./fixtures";
import { project } from "./geometry";
function DemoControls() {
  const s = store();
  const [scenario, setScenario] = useState("complete");
  useEffect(() => {
    if (!s.playing || !s.activeRoute?.feasible) return;
    const timer = setInterval(() => {
      const st = store.getState(),
        r = st.activeRoute;
      if (!r?.feasible || st.replan === "pending") {
        store.setState({ playing: false });
        return;
      }
      const i = Math.min(st.progress + 1, r.geometry.length - 1),
        p = r.geometry[i],
        next = r.geometry[Math.min(i + 1, r.geometry.length - 1)];
      const [x, y] = project(p, demoDem.projection),
        [nx, ny] = project(next, demoDem.projection);
      store.setState({
        progress: i,
        playing: i < r.geometry.length - 1,
        navigation: {
          position: p,
          heading_deg_clockwise_from_north:
            ((Math.atan2(nx - x, ny - y) * 180) / Math.PI + 360) % 360,
          next_waypoint: next,
        },
      });
    }, 180);
    return () => clearInterval(timer);
  }, [s.playing, s.activeRoute]);
  return (
    <section className="demo-panel">
      <div className="section-title">
        DEMO LAB <span>FIXTURES ONLY</span>
      </div>
      <label className="muted" htmlFor="scenario">
        Test scenario
      </label>
      <select
        id="scenario"
        value={scenario}
        onChange={(e) => {
          const value = e.target.value;
          setScenario(value);
          const view = store.getState().view;
          loadDemo();
          store.setState({ view });
          if (value === "no-dem") store.setState({ dem: undefined });
          if (value === "no-route")
            store
              .getState()
              .setActiveRoute({
                id: "no-route",
                feasible: false,
                segments: [],
                elevation_profile: [],
                alternatives: [],
                conflict_details: [],
                geometry: [],
                waypoints: [],
                target_ids: [],
                warnings: [],
                constraint_conflicts: [
                  "Synthetic scenario: constraints cannot be satisfied.",
                ],
              });
          if (value === "no-data")
            store.setState({
              dem: undefined,
              layers: [],
              layerSettings: {},
              activeRoute: undefined,
              alternatives: [],
              targets: [],
            });
          if (value === "bad-projection")
            store.setState({
              dem: {
                ...demoDem,
                projection: {
                  ...demoDem.projection,
                  kind: "unsupported" as any,
                },
              },
            });
          if (value === "image-error") {
            const st = store.getState();
            st.setLayers(
              st.layers.map((l, i) =>
                i
                  ? l
                  : {
                      ...l,
                      layer: { ...l.layer, uri: "/missing-fixture.png" },
                    },
              ),
            );
          }
        }}
      >
        <option value="complete">Complete synthetic mission</option>
        <option value="no-dem">Missing DEM</option>
        <option value="no-route">No feasible route</option>
        <option value="no-data">No data available</option>
        <option value="bad-projection">Unsupported 3D projection</option>
        <option value="image-error">Image load failure</option>
      </select>
      <div className="demo-buttons">
        <button
          onClick={() => {
            loadDemo();
            setScenario("complete");
          }}
        >
          Reset demo
        </button>
        <button onClick={applyFixtureResponse}>Apply fixture response</button>
      </div>
      <p className="muted">
        Response button selects a prerecorded path only if it matches the
        mission and avoids blocked rectangles. It is not a routing engine.
      </p>
      <button
        className="play-button"
        disabled={!s.activeRoute?.feasible || s.replan === "pending"}
        onClick={() => {
          const r = s.activeRoute;
          if (!r?.feasible) return;
          if (s.playing) store.setState({ playing: false });
          else {
            const progress =
              s.progress >= r.geometry.length - 1 ? 0 : s.progress;
            store.setState({
              playing: true,
              progress,
              navigation: {
                position: r.geometry[progress],
                heading_deg_clockwise_from_north: 0,
              },
            });
          }
        }}
      >
        {s.playing ? "Ⅱ Pause playback" : "▷ Play astronaut simulation"}
      </button>
      <progress
        aria-label="Navigation progress"
        max={Math.max(1, (s.activeRoute?.geometry.length ?? 1) - 1)}
        value={s.progress}
      />
      <small className="muted">
        Accelerated sample playback; no real positioning.
      </small>
    </section>
  );
}
export function Demo() {
  useEffect(() => {
    loadDemo();
  }, []);
  return <MarsMap demoControls={<DemoControls />} />;
}
export { mission };
