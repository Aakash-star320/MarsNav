import { lazy, Suspense, useEffect } from "react";
import { useMissionStore as store } from "../../store/missionStore";
import { Map2D } from "./Map2D";
import { label } from "./geometry";
import type { BlockedArea } from "../../types/contracts";
import type { Mode } from "./types";
import "./styles.css";
const Terrain3D = lazy(() =>
  import("./Terrain3D").then((m) => ({ default: m.Terrain3D })),
);
export type MarsMapProps = {
  onBlockedArea?: (area: BlockedArea) => void;
  demoControls?: React.ReactNode;
  /** Wording and slots for non-demo use. Omitted props keep the demo text. */
  workspace?: { eyebrow: string; title: string; subtitle: string };
  viewBar?: { eyebrow: string; title: string; detail?: string };
  badge?: string | null;
  caption?: string;
  sidebarExtra?: React.ReactNode;
  notes?: React.ReactNode;
};
const tools: [Mode, string, string][] = [
  ["inspect", "⌖", "Inspect"],
  ["base", "◉", "Base"],
  ["destination", "⚑", "Destination"],
  ["aoi", "▧", "Area"],
  ["blocked", "⊠", "Block"],
];
export function MarsMap({
  onBlockedArea,
  demoControls,
  workspace = {
    eyebrow: "MISSION WORKSPACE / 01",
    title: "Across the rim.",
    subtitle: "Local terrain reconnaissance",
  },
  viewBar = {
    eyebrow: "LOCAL REGION / SYNTHETIC CRATER",
    title: "Terrain explorer",
    detail: "18.44° N / 77.45° E",
  },
  badge = "SYNTHETIC DEMO",
  caption = "All terrain, layers and routes are synthetic",
  sidebarExtra,
  notes,
}: MarsMapProps) {
  const s = store();
  useEffect(() => {
    let ids = new Set(store.getState().blockedAreas.map((a) => a.id));
    return store.subscribe((next) => {
      const fresh = next.blockedAreas.filter((a) => !ids.has(a.id));
      ids = new Set(next.blockedAreas.map((a) => a.id));
      fresh.forEach((a) => onBlockedArea?.(a));
    });
  }, [onBlockedArea]);
  const selected = s.targets.find((t) => t.id === s.selectedTargetId);
  const visible = s.layers.filter(
    (l) => s.layerSettings[l.layer.id]?.visible,
  ).length;
  const message = s.draft
    ? "Review rectangle, then confirm."
    : s.mode === "aoi" || s.mode === "blocked"
      ? s.first
        ? "Select the opposite corner."
        : "Select the first corner."
      : s.mode === "base"
        ? "Click to set mission base."
        : s.mode === "destination"
          ? "Click to set destination."
          : "Select a target or inspect a coordinate.";
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" onClick={(e) => e.preventDefault()}>
          <span className="brand-icon">M</span>MARS<span>NAV</span>
          <small>SURFACE OPERATIONS</small>
        </a>
        <div className="top-right">
          <span className="status-dot" />
          LOCAL SESSION
          {badge && <span className="synthetic-badge">{badge}</span>}
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="mission-title">
            <div className="eyebrow">{workspace.eyebrow}</div>
            <h1>{workspace.title}</h1>
            <p>{workspace.subtitle}</p>
          </div>
          <section>
            <div className="section-title">
              MISSION GEOMETRY <span>01</span>
            </div>
            <div className="coordinate-row">
              <i className="dot base" />
              <div>
                <b>Base camp</b>
                <small>{label(s.base)}</small>
              </div>
              {s.base && (
                <button
                  className="icon-button"
                  aria-label="Clear base"
                  onClick={() => s.setBase(undefined)}
                >
                  ×
                </button>
              )}
            </div>
            <div className="coordinate-row">
              <i className="dot destination" />
              <div>
                <b>Destination</b>
                <small>{label(s.destination)}</small>
              </div>
              {s.destination && (
                <button
                  className="icon-button"
                  aria-label="Clear destination"
                  onClick={() => s.setDestination(undefined)}
                >
                  ×
                </button>
              )}
            </div>
            <div className="aoi-info">
              <span>
                {s.aoi ? "Area of interest selected" : "No area selected"}
              </span>
              {s.aoi && (
                <button
                  className="text-button"
                  onClick={() => s.setAoi(undefined)}
                >
                  Clear
                </button>
              )}
            </div>
          </section>
          {sidebarExtra}
          <section className="layer-section">
            <div className="section-title">
              SURFACE LAYERS <span>{visible} ON</span>
            </div>
            {!s.layers.length && (
              <p className="muted">No processed layers. Coverage is unknown.</p>
            )}
            {s.layers.map((entry) => {
              const l = entry.layer,
                settings = s.layerSettings[l.id],
                unavailable =
                  entry.coverage === "unavailable" || l.valid_percent <= 0;
              return (
                <div className="layer" key={l.id}>
                  <label className="layer-label">
                    <span
                      className="layer-icon"
                      style={{ background: entry.colors[0] }}
                    />
                    <span>{l.kind}</span>
                    <input
                      type="checkbox"
                      aria-label={`${l.kind} visibility`}
                      checked={settings?.visible ?? false}
                      disabled={unavailable}
                      onChange={(e) =>
                        s.setLayerVisibility(l.id, e.target.checked)
                      }
                    />
                  </label>
                  {settings?.visible && (
                    <div className="layer-detail">
                      <label>
                        Opacity{" "}
                        <output>{Math.round(settings.opacity * 100)}%</output>
                        <input
                          aria-label={`${l.kind} opacity`}
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={settings.opacity}
                          onChange={(e) =>
                            s.setLayerOpacity(l.id, Number(e.target.value))
                          }
                        />
                      </label>
                      <div
                        className="gradient"
                        style={{
                          background: `linear-gradient(90deg,${entry.colors.join(",")})`,
                        }}
                      />
                      <small>{entry.legend}</small>
                    </div>
                  )}
                  <details>
                    <summary>
                      {entry.coverage === "partial"
                        ? "Partial coverage"
                        : entry.coverage}{" "}
                      · {l.valid_percent.toFixed(1)}% valid
                    </summary>
                    <p>
                      {entry.source}
                      <br />
                      {entry.synthetic
                        ? "Synthetic fixture; not an observation."
                        : "Source-backed processed layer."}
                      <br />
                      Valid % refers to layer samples, not AOI coverage.
                      <br />
                      {s.layerStatus[l.id] ?? "Not loaded"}
                    </p>
                  </details>
                </div>
              );
            })}
          </section>
          <section>
            <div className="section-title">
              SCIENCE TARGETS <span>{s.targets.length}</span>
            </div>
            {!s.targets.length && <p className="muted">No targets loaded.</p>}
            {s.targets.map((t, i) => (
              <button
                className={`target-card ${s.selectedTargetId === t.id ? "selected" : ""}`}
                key={t.id}
                onClick={() =>
                  s.setSelectedTarget(
                    s.selectedTargetId === t.id ? undefined : t.id,
                  )
                }
              >
                <span className="target-number">0{i + 1}</span>
                <span>
                  <b>{t.title.replace(" · synthetic", "")}</b>
                  <small>Fixture target · evidence unavailable</small>
                </span>
                <span>↗</span>
              </button>
            ))}
            {selected && (
              <p className="muted">
                {label(selected.location)}
                <br />
                Confidence: {selected.confidence}. No scientific inference is
                made.
              </p>
            )}
          </section>
          <section>
            <div className="section-title">
              ROUTE / NAVIGATION <span>02</span>
            </div>
            <label className="check-row">
              <input
                type="checkbox"
                checked={s.showAlternatives}
                onChange={(e) =>
                  store.setState({ showAlternatives: e.target.checked })
                }
              />
              Show alternatives
            </label>
            {s.activeRoute?.feasible ? (
              <>
                <div className="metrics">
                  <div>
                    <strong>
                      {s.activeRoute.metrics
                        ? (s.activeRoute.metrics.distance_m / 1000).toFixed(2)
                        : "—"}
                    </strong>
                    <small>km · fixture route</small>
                  </div>
                  <div>
                    <strong>
                      {s.activeRoute.metrics?.estimated_duration_min ?? "—"}
                    </strong>
                    <small>min · fixture estimate</small>
                  </div>
                </div>
                <p className="muted">
                  {s.activeRoute.waypoints.length} waypoints · Not safety
                  assessed
                </p>
              </>
            ) : (
              <p className="warning">
                {s.activeRoute ? "No feasible route" : "No active route"}
                {s.activeRoute?.constraint_conflicts.map((c) => (
                  <small key={c}>{c}</small>
                ))}
              </p>
            )}
            {s.replan === "pending" && (
              <p className="warning">
                Replan pending. Amber route is the previous result, not a valid
                new plan.
              </p>
            )}
            {s.blockedAreas.map((b, i) => (
              <div className="blocked-card" key={b.id}>
                <span>
                  Blocked area {i + 1}
                  <small>{b.reason}</small>
                </span>
                <button
                  aria-label={`Remove blocked area ${i + 1}`}
                  onClick={() =>
                    store.setState({
                      blockedAreas: s.blockedAreas.filter((x) => x.id !== b.id),
                      replan: "pending",
                      playing: false,
                    })
                  }
                >
                  ×
                </button>
              </div>
            ))}
          </section>
          {demoControls}
          <div className="sidebar-foot">
            Mars planetocentric coordinates
            <br />
            East-positive longitude · No Earth CRS defaults
          </div>
        </aside>
        <main className="main-area">
          <div className="viewbar">
            <div>
              <div className="eyebrow">{viewBar.eyebrow}</div>
              <h2>
                {viewBar.title}{" "}
                {viewBar.detail && <span>{viewBar.detail}</span>}
              </h2>
            </div>
            <div className="view-switch" role="group" aria-label="Map view">
              <button
                className={s.view === "2d" ? "active" : ""}
                onClick={() => s.setView("2d")}
              >
                2D Map
              </button>
              <button
                className={s.view === "3d" ? "active" : ""}
                onClick={() => s.setView("3d")}
              >
                3D Terrain
              </button>
            </div>
          </div>
          <div className="canvas-shell">
            <div className="floating-tools">
              {tools.map(([mode, icon, title]) => (
                <button
                  key={mode}
                  title={title}
                  aria-label={title}
                  className={s.mode === mode ? "active" : ""}
                  onClick={() => s.setMode(mode)}
                >
                  <span>{icon}</span>
                  {title}
                </button>
              ))}
              <button
                title="Fit region"
                aria-label="Fit region"
                onClick={() => store.setState({ focus: Date.now() })}
              >
                <span>⛶</span>Fit
              </button>
            </div>
            {s.view === "2d" ? (
              <Map2D />
            ) : (
              <Suspense
                fallback={
                  <div className="empty-view">Loading terrain renderer…</div>
                }
              >
                <Terrain3D />
              </Suspense>
            )}
            <div className="map-caption">
              <span className="status-dot" />
              {s.view === "2d" ? "ANGULAR MAP" : "LOCAL DEM SURFACE"}
              <small>{caption}</small>
            </div>
            {s.view === "2d" && (
              <div className="north">
                N<br />
                <span>↑</span>
              </div>
            )}
            {(s.mode !== "inspect" || s.error) && (
              <div className="selection-panel">
                <b>{s.mode.toUpperCase()} SELECTION</b>
                <p>{s.error ?? message}</p>
                {s.mode === "blocked" && s.draft && (
                  <input
                    aria-label="Blocked area reason"
                    placeholder="Reason for blocking this area"
                    maxLength={500}
                    value={s.reason}
                    onChange={(e) => store.setState({ reason: e.target.value })}
                  />
                )}
                <div>
                  {s.draft && (
                    <button className="primary" onClick={s.confirm}>
                      Confirm {s.mode === "aoi" ? "AOI" : "block"}
                    </button>
                  )}
                  <button onClick={s.cancel}>Cancel</button>
                </div>
              </div>
            )}
            {s.view === "3d" && s.dem && (
              <label className="exaggeration">
                HEIGHT {s.exaggeration}×
                <input
                  aria-label="Vertical exaggeration"
                  type="range"
                  min="1"
                  max="3"
                  step="0.5"
                  value={s.exaggeration}
                  onChange={(e) =>
                    store.setState({ exaggeration: Number(e.target.value) })
                  }
                />
              </label>
            )}
            <div className="map-legend">
              <span>
                <i style={{ background: "#65e2c5" }} />
                Active route
              </span>
              <span>
                <i style={{ background: "#bda8fa" }} />
                Target
              </span>
              <span>
                <i style={{ background: "#f47e72" }} />
                Blocked
              </span>
            </div>
          </div>
          <div className="coordinate-strip">
            <span>⌖ {label(s.selectedPoint)}</span>
            <span>{s.mode === "inspect" ? "Click to inspect" : message}</span>
          </div>
          {notes ?? (
            <div className="bottom-note">
              <div>
                <span className="eyebrow">DATA INTEGRITY</span>
                <b>Missing coverage stays missing.</b>
                <p>
                  The northeast corner has no elevation samples. Terrain and
                  surface geometry are omitted there.
                </p>
              </div>
              <div>
                <span className="eyebrow">SHARED MISSION STATE</span>
                <b>One mission. Two perspectives.</b>
                <p>
                  Base, targets, routes and navigation remain synchronized
                  across map and terrain views.
                </p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
