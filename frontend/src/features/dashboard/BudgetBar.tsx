import type { Budget } from '../../utils/derive';
import { WALK_KMH, fmtDuration } from '../../utils/geo';

export default function BudgetBar({ b }: { b: Budget }) {
  return (
    <>
      <div className="bar">{b.a.map((x) => <i key={x.n} title={x.n} style={{ width: `${(x.m / b.T) * 100}%`, background: x.c }} />)}</div>
      <div className="lg">{b.a.map((x) => <span key={x.n}><s style={{ background: x.c }} />{x.n} {fmtDuration(x.m)}</span>)}</div>
      <p className="nt">
        Walking pace {WALK_KMH} km/h.{' '}
        {b.ok ? <span className="ok">Fits budget.</span> : <span className="bd">Exceeds budget.</span>}
      </p>
    </>
  );
}
