import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useStore } from '../../store/dashboardStore';
import type { Pt } from '../../types/ui';
import type { BoundingBox } from '../../types/contracts';
import { elevation, fmtCoord, lonLatToPx, pxToLonLat, slopeAt } from '../../utils/geo';
import { marsCtxLayer, marsTrekLayer } from '../mars-map/BaseImagery';
import { combined, segsOf } from '../../utils/derive';
import { setViewport } from '../../utils/viewport';

/**
 * The dashboard map: a real, zoomable and pannable Leaflet map (NASA Mars Trek imagery) with the planning
 * scene drawn on top. Planning state stays in canvas pixels (20 m each, see utils/geo.ts); an SVG overlay maps
 * those pixels onto the current map view, so every marker, route and analysis raster stays georeferenced while
 * you zoom. Reads shared state from the store and reports clicks/drags through store actions (mapPick, setRegion).
 */

const W = 800, H = 500;
const GRID = Array.from({ length: 40 * 25 }, (_, i) => ({ x: (i % 40) * 20, y: Math.floor(i / 40) * 20 }));

// Angular display CRS: 1 degree = 2^zoom screen pixels, latitude up (same convention as the Mars map module).
const crs: L.CRS = { ...L.CRS.Simple, code: 'MARS:CANONICAL_ANGULAR', distance() { throw Error('Metric calculations require explicit Mars projection'); } };
const toLatLng = (p: Pt): L.LatLngTuple => { const c = pxToLonLat(p); return [c.latitude_deg, c.longitude_deg_east]; };
const fromLatLng = (ll: L.LatLng): Pt => lonLatToPx({ latitude_deg: ll.lat, longitude_deg_east: ll.lng });

interface View { w: number; h: number; a: number; d: number; e: number; f: number }
const INITIAL: View = { w: 0, h: 0, a: 1, d: 1, e: 0, f: 0 };

const GridLayer = memo(function GridLayer({ id, op, slope }: { id: 'elev' | 'slope' | 'haz'; op: number; slope: number }) {
  const cells = useMemo(() => GRID.flatMap((g) => {
    const cx = g.x + 10, cy = g.y + 10;
    let fill: string;
    if (id === 'elev') { const v = (elevation(cx, cy) + 3300) / 1300; fill = `hsl(${200 - v * 160},60%,${25 + v * 35}%)`; }
    else if (id === 'slope') { fill = `hsl(${120 - Math.min(slopeAt(cx, cy), 30) * 4},70%,40%)`; }
    else { if (slopeAt(cx, cy) <= slope) return []; fill = '#e5645f'; }
    return [<rect key={`${g.x}-${g.y}`} x={g.x} y={g.y} width={20} height={20} fill={fill} />];
  }), [id, slope]);
  return <g opacity={op}>{cells}</g>;
});

/** A real analysis image (PNG from the backend) placed on the canvas by its geographic bounds. */
const RealRaster = memo(function RealRaster({ href, bounds, op }: { href: string; bounds: BoundingBox; op: number }) {
  const a = lonLatToPx({ latitude_deg: bounds.north_deg, longitude_deg_east: bounds.west_deg_east });
  const b = lonLatToPx({ latitude_deg: bounds.south_deg, longitude_deg_east: bounds.east_deg_east });
  return <image href={href} crossOrigin="anonymous" x={a.x} y={a.y} width={b.x - a.x} height={b.y - a.y} opacity={op} preserveAspectRatio="none" style={{ imageRendering: 'pixelated' }} />;
});

/** Draws children in screen pixels at a canvas position, so markers keep their size while the map zooms. */
function Pin({ p, k, children }: { p: Pt; k: View; children: ReactNode }) {
  return <g transform={`translate(${p.x} ${p.y}) scale(${1 / k.a} ${1 / k.d})`}>{children}</g>;
}
const pts = (p: Pt[]) => p.map((q) => `${q.x},${q.y}`).join(' ');
const NS = 'non-scaling-stroke';
const PIN = 'M0 0C-4-9-13-15-13-25a13 13 0 1 1 26 0c0 10-9 16-13 25z';

/** Google-Maps-style teardrop marker whose tip sits on the location, with an optional name tag. */
function Marker({ p, k, color, glyph, label, size = 1, onClick, hot, fg = '#fff' }: { p: Pt; k: View; color: string; fg?: string; glyph?: string; label?: string; size?: number; onClick?: () => void; hot?: boolean }) {
  return (
    <Pin p={p} k={k}>
      <g transform={`scale(${size})`} style={onClick ? { cursor: 'pointer', pointerEvents: 'all' } : undefined} onClick={onClick}>
        <ellipse cy={1} rx={7} ry={2.8} fill="#000" opacity={0.35} />
        <path d={PIN} fill={color} stroke={hot ? '#ffd166' : '#fff'} strokeWidth={hot ? 3 : 2} />
        <circle cy={-25} r={glyph ? 8.5 : 5} fill={glyph ? 'none' : '#fff'} />
        {glyph && <text y={-20.5} textAnchor="middle" fill={fg} fontSize={13} fontWeight={700}>{glyph}</text>}
      </g>
      {label && <Tag text={label} x={16 * size} y={-27 * size} />}
    </Pin>
  );
}
/** White name tag, like a map label. */
function Tag({ text, x, y }: { text: string; x: number; y: number }) {
  const w = text.length * 6.6 + 14;
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x={0} y={-11} width={w} height={22} rx={6} fill="#fff" stroke="#00000022" />
      <text x={7} y={4} fill="#1f2937" fontSize={12} fontWeight={600}>{text}</text>
    </g>
  );
}

const letter = (i: number) => String.fromCharCode(65 + (i % 26));

/** Index of the route vertex nearest to `p`, searching forward from `from` so stops stay in order. */
function nearestIdx(path: Pt[], p: Pt, from: number): number {
  let best = from, bd = Infinity;
  for (let i = from; i < path.length; i++) { const d = (path[i].x - p.x) ** 2 + (path[i].y - p.y) ** 2; if (d < bd) { bd = d; best = i; } }
  return best;
}
const fmtLeg = (km: number, min: number) => `${km < 1 ? Math.round(km * 1000) + ' m' : km.toFixed(2) + ' km'} · ${Math.max(1, Math.round(min))} min`;

/** Pill label for one leg of the route (distance and walking time), like a map's turn-by-turn legs. */
function LegPill({ text, p, k }: { text: string; p: Pt; k: View }) {
  const w = text.length * 6.4 + 16;
  return (
    <Pin p={p} k={k}>
      <g transform="translate(0 -14)">
        <rect x={-w / 2} y={-11} width={w} height={22} rx={11} fill="#0b1220" stroke="#fff" strokeOpacity={0.85} strokeWidth={1.5} />
        <text y={4} textAnchor="middle" fill="#fff" fontSize={11.5} fontWeight={600}>{text}</text>
      </g>
    </Pin>
  );
}

export default function MapCanvas() {
  const s = useStore();
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const imageryRef = useRef<L.GridLayer | null>(null);
  const ctxRef = useRef<L.GridLayer | null>(null);
  const coRef = useRef<HTMLDivElement>(null);
  const [k, setK] = useState<View>(INITIAL);
  const [rubber, setRubber] = useState<{ a: Pt; b: Pt } | null>(null);
  const L_ = s.layers;
  const drawing = s.pick === 'region';
  const only = s.showOnly;                 // set by "Show on map" in the assistant: everything else is hidden until the next plan
  const segs = only ? [] : segsOf(s);
  const stops = s.start && s.dest ? [s.start, ...s.wps, s.dest] : [];
  const main = s.mode === 'route' ? segs[0] : undefined;
  const legs = (() => {
    if (!main || stops.length < 2) return [] as { text: string; p: Pt }[];
    const path = main.s.p, st = main.s;
    if (path.length < 2) return [];
    const idx = [0]; for (let i = 1; i < stops.length - 1; i++) idx.push(nearestIdx(path, stops[i], idx[i - 1])); idx.push(path.length - 1);
    const total = st.cum[st.cum.length - 1] || 1;
    return idx.slice(1).map((e, i) => {
      const a = idx[i], km = (st.cum[e] ?? 0) - (st.cum[a] ?? 0);
      return { text: fmtLeg(km, st.t * (km / total)), p: path[Math.round((a + e) / 2)] };
    }).filter((l) => l.p);
  })();
  const steep = (x: { s: { p: Pt[]; over: number[] } }) => {
    const runs: Pt[][] = []; let cur: number[] = [];
    [...x.s.over].sort((a, b) => a - b).forEach((i) => { if (cur.length && i !== cur[cur.length - 1] + 1) { runs.push(cur.map((j) => x.s.p[j])); cur = []; } cur.push(i); });
    if (cur.length) runs.push(cur.map((j) => x.s.p[j]));
    return runs.filter((r) => r.length > 1);
  };
  const c = s.nav ? combined(s) : null;
  const navP = c && s.nav ? c.s.p[Math.min(s.nav.i, c.s.p.length - 1)] : null;
  const latest = useRef(s);
  latest.current = s;

  // Create the map once; keep the SVG overlay in step with the view.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const m = L.map(host, {
      crs, zoomControl: false, zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 100, zoomAnimation: false,
      minZoom: 3, maxZoom: 15, attributionControl: true, doubleClickZoom: true,
      maxBounds: [[-90, -180], [90, 180]], maxBoundsViscosity: 0.8,
    });
    mapRef.current = m;
    L.control.zoom({ position: 'bottomright' }).addTo(m);
    m.attributionControl.setPrefix(false);
    // Start wide: the imagery is 232 m/px, so fitting the 16 x 10 km frame would stretch it about 12x and look
    // blurry. At zoom 9 it is shown at about 3x, and "Fit" still zooms in to the planning frame.
    m.setView(toLatLng({ x: W / 2, y: H / 2 }), 9);

    let raf = 0;
    const sync = () => {
      raf = 0;
      const size = m.getSize();
      if (size.x < 2 || size.y < 2) return;          // hidden (the 3D view is showing): keep the last real view
      const at = (p: Pt) => m.latLngToContainerPoint(toLatLng(p));
      const p0 = at({ x: 0, y: 0 }), p1 = at({ x: W, y: H });
      const a = (p1.x - p0.x) / W, d = (p1.y - p0.y) / H;
      setK({ w: size.x, h: size.y, a, d, e: p0.x, f: p0.y });
      setViewport({ x: -p0.x / a, y: -p0.y / d, w: size.x / a, h: size.y / d });   // what 3D reads when no analysis exists yet
    };
    const queue = () => { if (!raf) raf = requestAnimationFrame(sync); };
    m.on('move zoom resize', queue);
    sync();
    const ro = new ResizeObserver(() => { m.invalidateSize(); queue(); });
    ro.observe(host);

    m.on('click', (e: L.LeafletMouseEvent) => { latest.current.mapPick(fromLatLng(e.latlng)); });
    m.on('mousemove', (e: L.LeafletMouseEvent) => {
      if (coRef.current) coRef.current.textContent = fmtCoord(fromLatLng(e.latlng));
    });
    m.on('mouseout', () => { if (coRef.current) coRef.current.textContent = 'Hover the map for coordinates'; });
    return () => { if (raf) cancelAnimationFrame(raf); ro.disconnect(); m.off(); m.remove(); mapRef.current = null; imageryRef.current = null; ctxRef.current = null; };
  }, []);

  // Real imagery layer follows the "Mars surface imagery" toggle and opacity.
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    if (!L_.opt.on) { imageryRef.current?.remove(); imageryRef.current = null; ctxRef.current?.remove(); ctxRef.current = null; return; }
    if (!imageryRef.current) { imageryRef.current = marsTrekLayer(L_.opt.op).addTo(m); imageryRef.current.setZIndex(1); }
    else imageryRef.current.setOpacity(L_.opt.op);
    if (!ctxRef.current) { ctxRef.current = marsCtxLayer(L_.opt.op).addTo(m); ctxRef.current.setZIndex(2); }
    else ctxRef.current.setOpacity(L_.opt.op);
  }, [L_.opt.on, L_.opt.op]);

  // Drag to draw a region only while "select region" is active; otherwise dragging pans the map.
  useEffect(() => {
    const m = mapRef.current, host = hostRef.current;
    if (!m || !host) return;
    if (!drawing) { m.dragging.enable(); host.style.cursor = ''; return; }
    m.dragging.disable();
    host.style.cursor = 'crosshair';
    let start: Pt | null = null, startScreen: L.Point | null = null;
    const at = (ev: PointerEvent) => { const cp = m.mouseEventToContainerPoint(ev); return { p: fromLatLng(m.containerPointToLatLng(cp)), cp }; };
    const down = (ev: PointerEvent) => {
      if (ev.button !== 0 || (ev.target as HTMLElement).closest('.leaflet-control')) return;
      const r = at(ev); start = r.p; startScreen = r.cp; host.setPointerCapture(ev.pointerId);
    };
    const move = (ev: PointerEvent) => { if (start) setRubber({ a: start, b: at(ev).p }); };
    const up = (ev: PointerEvent) => {
      if (!start || !startScreen) return;
      const r = at(ev), a = start, big = r.cp.distanceTo(startScreen) > 8;
      start = null; startScreen = null; setRubber(null);
      if (big) latest.current.setRegion({ x: Math.round(Math.min(a.x, r.p.x)), y: Math.round(Math.min(a.y, r.p.y)), w: Math.round(Math.abs(r.p.x - a.x)), h: Math.round(Math.abs(r.p.y - a.y)) });
    };
    host.addEventListener('pointerdown', down); host.addEventListener('pointermove', move); host.addEventListener('pointerup', up);
    return () => { host.removeEventListener('pointerdown', down); host.removeEventListener('pointermove', move); host.removeEventListener('pointerup', up); host.style.cursor = ''; setRubber(null); };
  }, [drawing]);

  // Bring a focused item (for example a selected target) into view.
  useEffect(() => {
    const m = mapRef.current;
    if (m && s.focus) m.setView(toLatLng(s.focus), s.focusZoom ?? Math.max(m.getZoom(), 12.5));
  }, [s.focus]);

  const fit = () => mapRef.current?.fitBounds([toLatLng({ x: 0, y: H }), toLatLng({ x: W, y: 0 })]);
  const world = `matrix(${k.a} 0 0 ${k.d} ${k.e} ${k.f})`;

  return (
    <>
      <div id="map" ref={hostRef} className="leafmap" />
      <svg id="mapov" width={k.w} height={k.h} viewBox={`0 0 ${k.w || 1} ${k.h || 1}`}>
        <g transform={world}>
          {L_.elev.on && (s.real ? <RealRaster href={s.real.layers.elevation.href} bounds={s.real.layers.elevation.bounds} op={L_.elev.op} /> : <GridLayer id="elev" op={L_.elev.op} slope={s.slope} />)}
          {L_.slope.on && (s.real ? <RealRaster href={s.real.layers.slope.href} bounds={s.real.layers.slope.bounds} op={L_.slope.op} /> : <GridLayer id="slope" op={L_.slope.op} slope={s.slope} />)}
          {L_.haz.on && (s.real ? <RealRaster href={`${s.real.hazardBase}?slope_limit_deg=${s.slope}`} bounds={s.real.layers.elevation.bounds} op={L_.haz.op} /> : <GridLayer id="haz" op={L_.haz.op} slope={s.slope} />)}
          {L_.spec.on && s.real?.layers.science && <RealRaster href={s.real.layers.science.href} bounds={s.real.layers.science.bounds} op={L_.spec.op} />}
          {!s.real && !s.online && <rect x={0} y={0} width={W} height={H} fill="none" stroke="#ffffff" strokeOpacity={0.55} strokeWidth={1.5} strokeDasharray="2 6" vectorEffect={NS} />}
          {!s.real && !s.online && k.a * W > 420 && <Pin p={{ x: 0, y: 0 }} k={k}><text x={6} y={16} fill="#fff" fillOpacity={0.8} fontSize={11} stroke="#0b1220" strokeWidth={3} paintOrder="stroke">Planning area · 16 × 10 km (routes are simulated inside it)</text></Pin>}
          {s.region && <rect x={s.region.x} y={s.region.y} width={s.region.w} height={s.region.h} fill="none" stroke="#2dd4d0" strokeWidth={2} strokeDasharray="8 4" vectorEffect={NS} />}
          {!only && s.obs.map((o, i) => (
            <g key={i}>
              <circle cx={o.x} cy={o.y} r={o.r} fill="#e5645f55" stroke="#e5645f" strokeWidth={2} strokeDasharray="3 3" vectorEffect={NS} />
              <Pin p={o} k={k}><text y={4} fill="#fff" fontSize={11} textAnchor="middle">Obstacle</text></Pin>
            </g>
          ))}
          {!only && s.prev && <polyline points={pts(s.prev)} fill="none" stroke="#fff" strokeWidth={2} strokeDasharray="2 5" opacity={0.6} vectorEffect={NS} />}
          {!only && s.mode === 'route' && s.routes.map((r, i) => i !== s.sel && <polyline key={r.k} points={pts(r.out.p)} fill="none" stroke={r.c} strokeWidth={2} opacity={0.45} vectorEffect={NS} />)}
          {segs.map((x, i) => <polyline key={'c' + i} points={pts(x.s.p)} fill="none" stroke="#0b1220" strokeOpacity={0.85} strokeWidth={x.dashed ? 6 : 9} strokeLinecap="round" strokeLinejoin="round" vectorEffect={NS} />)}
          {segs.map((x, i) => <polyline key={i} points={pts(x.s.p)} fill="none" stroke={x.c} strokeWidth={x.dashed ? 3 : 5} strokeDasharray={x.dashed ? '9 5' : undefined} strokeLinecap="round" strokeLinejoin="round" vectorEffect={NS} />)}
          {segs.filter((x) => !x.dashed).flatMap((x, i) => steep(x).map((r, j) => <polyline key={`st${i}-${j}`} points={pts(r)} fill="none" stroke="#fbbf24" strokeWidth={5} strokeLinecap="round" strokeLinejoin="round" vectorEffect={NS}><title>Steeper than the slope limit</title></polyline>))}
          {legs.map((l, i) => <LegPill key={i} text={l.text} p={l.p} k={k} />)}
          {s.targets.filter((t) => !only || t.id === only.id).map((t) => {
            const o = s.mission?.feasible ? s.mission.legs.findIndex((l) => l.t === t) : -1;
            return <Marker key={t.id} p={t} k={k} color="#8b5cf6" glyph={o >= 0 ? String(o + 1) : '★'} label={t.label ?? t.id} hot={s.selT === t.id} onClick={() => s.selectTarget(t.id)} />;
          })}
          {!only && s.wps.map((w, i) => <Marker key={i} p={w} k={k} color="#fff" fg="#0b1220" glyph={letter(i + 1)} size={0.85} />)}
          {!only && <Marker p={s.base} k={k} color="#2563eb" glyph="⌂" label="Base" />}
          {!only && s.start && <Marker p={s.start} k={k} color="#16a34a" glyph="A" label="Start" />}
          {!only && s.dest && <Marker p={s.dest} k={k} color="#dc2626" glyph={letter(s.wps.length + 1)} label="Destination" />}
          {s.focus && <Pin p={s.focus} k={k}><circle r={22} fill="#e8aa3c33" stroke="#e8aa3c" strokeWidth={2} /></Pin>}
          {navP && <Pin p={navP} k={k}><circle r={16} fill="#4285f4" opacity={0.22} /><circle r={8} fill="#4285f4" stroke="#fff" strokeWidth={3} /><Tag text="Simulated astronaut" x={14} y={-14} /></Pin>}
          {rubber && <rect x={Math.min(rubber.a.x, rubber.b.x)} y={Math.min(rubber.a.y, rubber.b.y)} width={Math.abs(rubber.b.x - rubber.a.x)} height={Math.abs(rubber.b.y - rubber.a.y)} fill="#2dd4d022" stroke="#2dd4d0" strokeDasharray="6 3" vectorEffect={NS} />}
        </g>
      </svg>
      <div className="mtools">
        <button className={drawing ? 'on' : ''} onClick={() => s.setPick(drawing ? null : 'region')} title="Drag a box on the map to choose the analysis area">▭ {drawing ? 'Drawing: drag on map' : 'Select region'}</button>
        <button onClick={fit} title="Zoom to the planning area">⌖ Fit</button>
          {only && <button onClick={() => s.setField('showOnly', null)} title="Show the routes, sites and markers again">Show all</button>}
      </div>
      <div className="ov" id="co" ref={coRef}>Hover the map for coordinates</div>
    </>
  );
}
