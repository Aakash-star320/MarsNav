import { memo, useMemo, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { useStore } from '../../store/dashboardStore';
import type { Pt } from '../../types/ui';
import type { BoundingBox } from '../../types/contracts';
import { elevation, fmtCoord, lonLatToPx, pxToLonLat, slopeAt } from '../../utils/geo';
import { trekTilesFor, trekUrl } from '../../utils/trek';
import { combined, segsOf } from '../../utils/derive';

/**
 * Stand-in for the separate interactive map component. Integration contract:
 * reads shared state (region, markers, routes, obstacles, layers, focus, nav position) from the store
 * and reports clicks/drags through store actions (mapPick, setRegion). Swap this file for Leaflet/Cesium.
 */

const GRID = Array.from({ length: 40 * 25 }, (_, i) => ({ x: (i % 40) * 20, y: Math.floor(i / 40) * 20 }));

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

/** Real Mars surface imagery (NASA Mars Trek, Viking MDIM 232 m) behind the 800 x 500 planning canvas. */
const RealImagery = memo(function RealImagery({ op }: { op: number }) {
  const tiles = useMemo(() => {
    const nw = pxToLonLat({ x: 0, y: 0 }), se = pxToLonLat({ x: 800, y: 500 });
    return trekTilesFor(7, nw.longitude_deg_east, se.latitude_deg, se.longitude_deg_east, nw.latitude_deg).map((t) => {
      const a = lonLatToPx({ latitude_deg: t.north, longitude_deg_east: t.west });
      const b = lonLatToPx({ latitude_deg: t.south, longitude_deg_east: t.east });
      return { key: `${t.row}-${t.col}`, href: trekUrl(t), x: a.x, y: a.y, w: b.x - a.x + 0.6, h: b.y - a.y + 0.6 };
    });
  }, []);
  return (
    <g opacity={op}>
      {tiles.map((t) => <image key={t.key} href={t.href} x={t.x} y={t.y} width={t.w} height={t.h} preserveAspectRatio="none" />)}
      <rect width={800} height={500} fill="#0b1220" opacity={0.12} />
    </g>
  );
});

/** A real analysis image (PNG from the backend) placed on the canvas by its geographic bounds. */
const RealRaster = memo(function RealRaster({ href, bounds, op }: { href: string; bounds: BoundingBox; op: number }) {
  const a = lonLatToPx({ latitude_deg: bounds.north_deg, longitude_deg_east: bounds.west_deg_east });
  const b = lonLatToPx({ latitude_deg: bounds.south_deg, longitude_deg_east: bounds.east_deg_east });
  return <image href={href} x={a.x} y={a.y} width={b.x - a.x} height={b.y - a.y} opacity={op} preserveAspectRatio="none" style={{ imageRendering: 'pixelated' }} />;
});

function Label({ p, text, fill = '#fff' }: { p: Pt; text: string; fill?: string }) {
  return <text x={p.x + 11} y={p.y + 4} fill={fill} fontSize={12} fontWeight={600} stroke="#0b1220" strokeWidth={3} paintOrder="stroke">{text}</text>;
}
const pts = (p: Pt[]) => p.map((q) => `${q.x},${q.y}`).join(' ');

export default function MapCanvas() {
  const s = useStore();
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<Pt | null>(null);
  const [rubber, setRubber] = useState<{ a: Pt; b: Pt } | null>(null);
  const [coord, setCoord] = useState<Pt | null>(null);
  const L = s.layers;
  const regionMode = s.pick === 'region' || (s.mode === 'analyze' && !s.pick);
  const segs = segsOf(s);
  const c = s.nav ? combined(s) : null;
  const navP = c && s.nav ? c.s.p[Math.min(s.nav.i, c.s.p.length - 1)] : null;
  const cov = s.region ?? { x: s.base.x - 200, y: s.base.y - 150, w: 400, h: 300 };

  const toPt = (e: PointerEvent): Pt => {
    const svg = svgRef.current as SVGSVGElement, p = svg.createSVGPoint();
    p.x = e.clientX; p.y = e.clientY;
    const q = p.matrixTransform((svg.getScreenCTM() as DOMMatrix).inverse());
    return { x: Math.round(q.x), y: Math.round(q.y) };
  };

  return (
    <>
      <svg id="map" ref={svgRef} viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice"
        onPointerDown={(e) => { dragRef.current = toPt(e); }}
        onPointerMove={(e) => { const p = toPt(e); setCoord(p); if (dragRef.current && regionMode) setRubber({ a: dragRef.current, b: p }); }}
        onPointerUp={(e) => {
          const a = dragRef.current, b = toPt(e);
          dragRef.current = null; setRubber(null);
          if (!a) return;
          if (regionMode && Math.hypot(b.x - a.x, b.y - a.y) > 12) { s.setRegion({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y) }); return; }
          s.mapPick(b);
        }}>
        <rect width={800} height={500} fill="#0d1420" />
        {L.opt.on && <RealImagery op={L.opt.op} />}
        {L.elev.on && (s.real ? <RealRaster href={s.real.layers.elevation.href} bounds={s.real.layers.elevation.bounds} op={L.elev.op} /> : <GridLayer id="elev" op={L.elev.op} slope={s.slope} />)}
        {L.slope.on && (s.real ? <RealRaster href={s.real.layers.slope.href} bounds={s.real.layers.slope.bounds} op={L.slope.op} /> : <GridLayer id="slope" op={L.slope.op} slope={s.slope} />)}
        {L.haz.on && (s.real ? <RealRaster href={`${s.real.hazardBase}?slope_limit_deg=${s.slope}`} bounds={s.real.layers.elevation.bounds} op={L.haz.op} /> : <GridLayer id="haz" op={L.haz.op} slope={s.slope} />)}
        {L.spec.on && s.real?.layers.science && <RealRaster href={s.real.layers.science.href} bounds={s.real.layers.science.bounds} op={L.spec.op} />}
        {L.therm.on && <ellipse cx={260} cy={190} rx={150} ry={90} fill="#e0603a" opacity={L.therm.op * 0.7} />}
        {L.cov.on && (
          <g opacity={L.cov.op}>
            <rect width={800} height={500} fill="#6b7a94" />
            <rect x={cov.x - 150} y={cov.y - 120} width={cov.w + 300} height={cov.h + 240} fill="#e8aa3c" />
            <rect x={cov.x} y={cov.y} width={cov.w} height={cov.h} fill="#2dd4d0" />
          </g>
        )}
        {s.region && <rect x={s.region.x} y={s.region.y} width={s.region.w} height={s.region.h} fill="none" stroke="#2dd4d0" strokeWidth={2} strokeDasharray="8 4" />}
        {s.obs.map((o, i) => (
          <g key={i}>
            <circle cx={o.x} cy={o.y} r={o.r} fill="#e5645f55" stroke="#e5645f" strokeWidth={2} strokeDasharray="3 3" />
            <text x={o.x} y={o.y + 4} fill="#fff" fontSize={11} textAnchor="middle">Obstacle</text>
          </g>
        ))}
        {s.prev && <polyline points={pts(s.prev)} fill="none" stroke="#fff" strokeWidth={2} strokeDasharray="2 5" opacity={0.6} />}
        {s.mode === 'route' && s.routes.map((r, i) => i !== s.sel && <polyline key={r.k} points={pts(r.out.p)} fill="none" stroke={r.c} strokeWidth={2} opacity={0.45} />)}
        {segs.map((x, i) => <polyline key={i} points={pts(x.s.p)} fill="none" stroke={x.c} strokeWidth={x.dashed ? 3 : 5} strokeDasharray={x.dashed ? '9 5' : undefined} strokeLinecap="round" />)}
        {s.targets.map((t) => {
          const o = s.mission?.feasible ? s.mission.legs.findIndex((l) => l.t === t) : -1;
          return (
            <g key={t.id}>
              <rect x={t.x - 6} y={t.y - 6} width={12} height={12} fill={s.selT === t.id ? '#fff' : '#c0653a'} stroke="#fff" transform={`rotate(45 ${t.x} ${t.y})`} style={{ cursor: 'pointer' }} onClick={() => s.selectTarget(t.id)} />
              <Label p={t} text={o >= 0 ? `${o + 1}. ${t.id}` : t.id} fill="#f3d9c8" />
            </g>
          );
        })}
        {s.wps.map((w, i) => <g key={i}><circle cx={w.x} cy={w.y} r={6} fill="#e8aa3c" stroke="#fff" /><Label p={w} text={`WP${i + 1}`} /></g>)}
        <rect x={s.base.x - 7} y={s.base.y - 7} width={14} height={14} fill="#fff" /><Label p={s.base} text="Base" />
        {s.start && <g><circle cx={s.start.x} cy={s.start.y} r={7} fill="#2dd4d0" stroke="#fff" strokeWidth={2} /><Label p={s.start} text="Start" /></g>}
        {s.dest && <g><circle cx={s.dest.x} cy={s.dest.y} r={10} fill="none" stroke="#2dd4d0" strokeWidth={3} /><Label p={s.dest} text="Destination" /></g>}
        {s.focus && <circle cx={s.focus.x} cy={s.focus.y} r={22} fill="#e8aa3c33" stroke="#e8aa3c" strokeWidth={2} />}
        {navP && <g><circle cx={navP.x} cy={navP.y} r={8} fill="#fff" stroke="#2dd4d0" strokeWidth={3} /><text x={navP.x + 12} y={navP.y - 8} fill="#fff" fontSize={12} stroke="#0b1220" strokeWidth={3} paintOrder="stroke">Simulated astronaut</text></g>}
        {rubber && <rect x={Math.min(rubber.a.x, rubber.b.x)} y={Math.min(rubber.a.y, rubber.b.y)} width={Math.abs(rubber.b.x - rubber.a.x)} height={Math.abs(rubber.b.y - rubber.a.y)} fill="#2dd4d022" stroke="#2dd4d0" strokeDasharray="6 3" />}
      </svg>
      <div className="ov" id="co">{coord ? fmtCoord(coord) : 'Hover the map for coordinates'}</div>
    </>
  );
}
