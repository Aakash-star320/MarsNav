import { useEffect, useRef, useState } from 'react';
import { useStore } from '../../store/dashboardStore';
import { combined } from '../../utils/derive';

/** One main chart that follows the selected route or mission. mode="slope" shows signed slope vs limit. */
export default function ElevationChart({ mode }: { mode: 'elev' | 'slope' }) {
  const s = useStore();
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: 170 });
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => { const w = Math.max(320, el.clientWidth), h = Math.max(120, el.clientHeight); setSize((o) => (o.w === w && o.h === h ? o : { w, h })); });
    ro.observe(el);
    return () => ro.disconnect();
  });
  const c = combined(s);
  if (!c) return <p className="nt">Generate a route or plan a mission to see the profile.</p>;
  const st = c.s, sl = mode === 'slope', v = sl ? st.sl : st.el, W = size.w, H = size.h - 16, N = v.length - 1;
  const mn = sl ? -Math.max(s.slope + 3, ...v.map(Math.abs)) : Math.min(...v) - 15;
  const mx = sl ? -mn : Math.max(...v) + 15;
  const X = (i: number) => 64 + (st.cum[i] / st.d) * (W - 90);
  const Y = (q: number) => 10 + ((mx - q) / (mx - mn)) * (H - 32);
  const path = v.map((q, i) => `${i ? 'L' : 'M'}${X(i)} ${Y(q)}`).join('');
  const base = Y(sl ? 0 : mn), unit = sl ? '°' : ' m';

  const onMove = (e: React.MouseEvent) => {
    const r = (ref.current as SVGSVGElement).getBoundingClientRect(), x = ((e.clientX - r.left) / r.width) * W;
    let i = 0;
    while (i < N && X(i) < x) i++;
    setHover(i);
    s.setFocus(st.p[i]); // highlights the matching location on the map
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 170 }}>
      <div className="nt" style={{ margin: '0 0 6px', fontSize: 13.5 }}>
        {sl ? `Slope (° uphill +, downhill −); limit ±${s.slope}°`
          : `Elevation (m) vs distance (km): min ${Math.min(...st.el).toFixed(0)} m, max ${Math.max(...st.el).toFixed(0)} m, ascent ${st.up.toFixed(0)} m, descent ${st.dn.toFixed(0)} m`}. Hover to locate on the map.
      </div>
      <div ref={boxRef} style={{ flex: 1, minHeight: 130, position: 'relative' }}>
      <svg ref={ref} width={size.w} height={size.h} style={{ position: 'absolute', inset: 0 }} onMouseMove={onMove} onMouseLeave={() => { setHover(null); s.setFocus(null); }}>
        <path d={`${path}L${X(N)} ${base}L${X(0)} ${base}Z`} fill="#2dd4d0" opacity={0.15} />
        <path d={path} fill="none" stroke="#2dd4d0" strokeWidth={2.5} />
        {sl && [s.slope, -s.slope].map((q) => <line key={q} x1={64} x2={W - 24} y1={Y(q)} y2={Y(q)} stroke="#e5645f" strokeDasharray="4 3" />)}
        {c.b.slice(1).map((i) => <line key={i} x1={X(i)} x2={X(i)} y1={10} y2={H - 20} stroke="#b4c1d8" strokeDasharray="2 3" />)}
        {c.sg.map((x, i) => x.t && <text key={i} x={X(c.b[i] + x.s.p.length - 1) - 8} y={20} fill="#e8aa3c" fontSize={13}>◆{x.t.label ?? x.t.id}</text>)}
        <line x1={64} x2={64} y1={10} y2={H - 20} stroke="#2a3a57" /><line x1={64} x2={W - 24} y1={H - 20} y2={H - 20} stroke="#2a3a57" />
        <text x={4} y={20} fill="#b4c1d8" fontSize={13}>{mx.toFixed(0)}{unit}</text>
        <text x={4} y={H - 16} fill="#b4c1d8" fontSize={13}>{mn.toFixed(0)}{unit}</text>
        <text x={64} y={H + 8} fill="#b4c1d8" fontSize={13}>0 km</text>
        <text x={W - 70} y={H + 8} fill="#b4c1d8" fontSize={13}>{st.d.toFixed(1)} km</text>
        {hover !== null && (
          <>
            <line x1={X(hover)} x2={X(hover)} y1={10} y2={H - 20} stroke="#fff" opacity={0.7} />
            <text x={Math.min(X(hover) + 6, W - 210)} y={H - 4} fill="#fff" fontSize={14}>
              {`${st.cum[hover].toFixed(2)} km · ${st.el[hover].toFixed(0)} m · slope ${st.sl[hover].toFixed(1)}°`}
            </text>
          </>
        )}
      </svg>
      </div>
    </div>
  );
}
