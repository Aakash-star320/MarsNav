import { useEffect, useRef } from "react";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useMissionStore as store } from "../../store/missionStore";
import { latLng, validateBounds } from "./geometry";
import type { BoundingBox, LonLat } from "../../types/contracts";
const crs: L.CRS = {
  ...L.CRS.Simple,
  code: "MARS:CANONICAL_ANGULAR",
  distance() {
    throw Error("Metric calculations require explicit Mars projection");
  },
};
const bounds = (b: BoundingBox): L.LatLngBoundsExpression => [
  [b.south_deg, b.west_deg_east],
  [b.north_deg, b.east_deg_east],
];
export function Map2D() {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map>();
  const images = useRef(new Map<string, L.ImageOverlay>());
  const s = store();
  useEffect(() => {
    if (!host.current) return;
    const m = L.map(host.current, {
      crs,
      center: [18.44, 77.45],
      zoom: 14,
      zoomSnap: 0.1,
      zoomDelta: 0.5,
      minZoom: 1,
      maxZoom: 21,
      zoomControl: false,
      maxBounds: [
        [-90, -180],
        [90, 180],
      ],
    });
    map.current = m;
    L.control.zoom({ position: "bottomright" }).addTo(m);
    m.attributionControl.addAttribution(
      "Mars angular display • synthetic local fixtures",
    );
    const click = (e: L.LeafletMouseEvent) =>
      store
        .getState()
        .pick({
          latitude_deg: e.latlng.lat,
          longitude_deg_east:
            ((((e.latlng.lng + 180) % 360) + 360) % 360) - 180,
        });
    m.on("click", click);
    const ro = new ResizeObserver(() => m.invalidateSize());
    ro.observe(host.current);
    return () => {
      ro.disconnect();
      m.off();
      m.remove();
      map.current = undefined;
    };
  }, []);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    let live = true;
    const local = new Map<string, L.ImageOverlay>();
    images.current = local;
    const update = (id: string, text: string) => {
      if (live)
        store.setState((t) => ({
          layerStatus: { ...t.layerStatus, [id]: text },
        }));
    };
    s.layers.forEach(({ layer: l, projection, format, coverage }, i) => {
      try {
        validateBounds(l.bounds);
        if (projection !== "MARS:CANONICAL_ANGULAR" || format !== "image")
          throw Error("Unsupported projection / format");
        if (coverage === "unavailable" || l.valid_percent <= 0)
          throw Error("No valid coverage");
        const url = new URL(l.uri, location.href);
        if (!["http:", "https:", "blob:"].includes(url.protocol))
          throw Error("Unsupported asset URL");
        const img = L.imageOverlay(url.href, bounds(l.bounds), {
          interactive: false,
          zIndex: i,
        });
        img.on("load", () => update(l.id, "ready"));
        img.on("error", () => {
          img.remove();
          update(l.id, "Image unavailable");
        });
        local.set(l.id, img);
        update(l.id, "Not loaded");
      } catch (e) {
        update(l.id, (e as Error).message);
      }
    });
    return () => {
      live = false;
      local.forEach((img) => {
        img.off();
        img.remove();
      });
      local.clear();
    };
  }, [s.layers]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    images.current.forEach((img, id) => {
      const setting = s.layerSettings[id];
      if (setting?.visible) {
        img.setOpacity(setting.opacity);
        if (!m.hasLayer(img)) img.addTo(m);
      } else img.remove();
    });
  }, [s.layers, s.layerSettings]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const g = L.layerGroup().addTo(m);
    const mark = (
      p: LonLat,
      color: string,
      text: string,
      selected = false,
      click?: () => void,
    ) => {
      const el = document.createElement("span");
      el.textContent = text;
      const marker = L.circleMarker(latLng(p), {
        radius: selected ? 11 : 7,
        color: selected ? "#fff" : color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.95,
        bubblingMouseEvents: false,
      })
        .bindTooltip(el)
        .addTo(g);
      if (click) marker.on("click", click);
    };
    if (s.showAlternatives)
      s.alternatives
        .filter((r) => r.id !== s.activeRoute?.id && r.feasible)
        .forEach((r) =>
          L.polyline(r.geometry.map(latLng), {
            color: "#9aa6b8",
            weight: 2,
            dashArray: "6 8",
            interactive: false,
          }).addTo(g),
        );
    if (s.activeRoute?.feasible) {
      L.polyline(s.activeRoute.geometry.map(latLng), {
        color: s.replan === "pending" ? "#e8ab55" : "#65e2c5",
        weight: 4,
        dashArray: s.replan === "pending" ? "8 6" : undefined,
        interactive: false,
      }).addTo(g);
      s.activeRoute.waypoints.forEach((p, i) =>
        mark(p, "#65e2c5", `Waypoint ${i + 1}`),
      );
    }
    if (s.aoi)
      L.rectangle(bounds(s.aoi), {
        color: "#7b94a2",
        weight: 1,
        dashArray: "4 6",
        fill: false,
        interactive: false,
      }).addTo(g);
    s.blockedAreas.forEach((b) =>
      L.rectangle(bounds(b.bounds), {
        color: "#f47e72",
        fillOpacity: 0.25,
        weight: 2,
        interactive: false,
      }).addTo(g),
    );
    if (s.draft)
      L.rectangle(bounds(s.draft), {
        color: "#ffd28a",
        dashArray: "5 5",
        fillOpacity: 0.15,
        interactive: false,
      }).addTo(g);
    if (s.first) mark(s.first, "#ffd28a", "First corner");
    if (s.base) mark(s.base, "#c8efff", "BASE");
    if (s.destination) mark(s.destination, "#f6bd79", "DESTINATION");
    s.targets.forEach((t) =>
      mark(t.location, "#bda8fa", t.title, t.id === s.selectedTargetId, () =>
        s.setSelectedTarget(t.id),
      ),
    );
    if (s.selectedPoint) mark(s.selectedPoint, "#fff", "Selected coordinate");
    if (s.navigation) {
      const h = s.navigation.heading_deg_clockwise_from_north;
      L.marker(latLng(s.navigation.position), {
        icon: L.divIcon({
          className: "astronaut-icon",
          html: `<span style="transform:rotate(${h}deg)">▲</span>`,
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        interactive: false,
      }).addTo(g);
    }
    return () => {
      g.clearLayers();
      g.remove();
    };
  }, [
    s.activeRoute,
    s.alternatives,
    s.showAlternatives,
    s.targets,
    s.selectedTargetId,
    s.base,
    s.destination,
    s.aoi,
    s.draft,
    s.first,
    s.selectedPoint,
    s.blockedAreas,
    s.navigation,
    s.replan,
  ]);
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const b = s.aoi ?? s.layers[0]?.layer.bounds;
    if (b) m.fitBounds(bounds(b), { padding: [45, 45], animate: false });
  }, [s.focus, s.aoi]);
  useEffect(() => {
    const t = s.targets.find((t) => t.id === s.selectedTargetId);
    if (t) map.current?.panTo(latLng(t.location));
  }, [s.selectedTargetId, s.targets]);
  return (
    <div
      className="map-surface"
      ref={host}
      role="region"
      aria-label="2D Mars map"
      data-testid="map-2d"
    />
  );
}
