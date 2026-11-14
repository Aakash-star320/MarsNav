import { useEffect, useRef } from 'react';
import { useStore } from '../../store/dashboardStore';
import type { ChatAction, ChatCard } from '../../types/ui';

const SUGGESTIONS: { icon: string; title: string; desc: string; q: string }[] = [
  { icon: '◎', title: 'Analyze this region', desc: 'Read real terrain and screen for hydrated minerals', q: 'Analyze this region' },
  { icon: '⤳', title: 'Find the safest route', desc: 'Compare routes by slope and terrain risk', q: 'Find the safest route' },
  { icon: '✦', title: 'Plan a 4-hour mission', desc: 'Pick mineral sites and return to base', q: 'I have four hours of oxygen; find mineral sites and return to base' },
  { icon: '◬', title: 'Why hydrated minerals?', desc: 'What they tell us about Mars', q: 'Why are hydrated minerals important?' },
];

function Sparkle({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2l1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9L12 2z" fill="currentColor" />
      <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15z" fill="currentColor" opacity=".7" />
    </svg>
  );
}

function Actions({ actions }: { actions: ChatAction[] }) {
  const show = useStore((s) => s.showOnMap);
  return (
    <div className="cx-actions">
      {actions.map((a, i) => <button key={i} className={'cx-act' + (a.open ? ' alt' : '')} onClick={() => show(a)}><span>{a.open ? '☰' : '⌖'}</span>{a.label}</button>)}
    </div>
  );
}

function Card({ card }: { card: ChatCard }) {
  const show = useStore((s) => s.showOnMap);
  return (
    <div className="cx-res">
      <div className="cx-stats">{card.stats.map(([k, v]) => <div key={k}><small>{k}</small><b>{v}</b></div>)}</div>
      {card.targets.length > 0 && (
        <div className="cx-tg">
          <h4>Candidates</h4>
          {card.targets.map((t) => (
            <div key={t.id} className="cx-t">
              <div className="cx-t-h"><b>{t.label}</b><span className="cx-pill">{t.score}%</span><span className="cx-pill soft">{t.conf} confidence</span>
                <button className="cx-mini" onClick={() => show({ label: t.label, at: t.at, id: t.id })}>⌖ Show</button></div>
              {t.evidence && <p>{t.evidence}</p>}
            </div>
          ))}
        </div>
      )}
      {card.warnings.length > 0 && (
        <details className="cx-warn"><summary>{card.warnings.length} note{card.warnings.length > 1 ? 's' : ''} and limitations</summary>
          {card.warnings.map((w, i) => <p key={i}>{w}</p>)}
        </details>
      )}
    </div>
  );
}

function JobCard() {
  const job = useStore((s) => s.job);
  if (!job) return null;
  const pct = Math.round(((job.i + 0.5) / job.stages.length) * 100);
  return (
    <div className="cx-job">
      <div className="cx-job-h"><i className="cx-pulse" />{job.title}<em>{job.stages[Math.min(job.i, job.stages.length - 1)]}</em></div>
      <div className="cx-prog"><i style={{ width: `${Math.min(100, pct)}%` }} /></div>
    </div>
  );
}

export default function ChatPanel() {
  const { aiOpen, toggleAi, chat, aiDraft, setAiDraft, sendChat, online, clearChat } = useStore();
  const endRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [chat.length, aiOpen]);
  useEffect(() => {                                   // composer grows with its text, up to a limit
    const el = boxRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(160, el.scrollHeight) + 'px';
  }, [aiDraft, aiOpen]);
  if (!aiOpen) return null;
  const send = () => { if (aiDraft.trim()) sendChat(aiDraft); };
  return (
    <aside id="C" aria-label="MarsNav assistant">
      <header className="cx-head">
        <span className="cx-orb"><Sparkle size={17} /></span>
        <div className="cx-title"><b>MarsNav Assistant</b>
          <span className={'cx-mode' + (online ? '' : ' off')} title="The assistant only runs the verified actions the buttons run. It does not use a language model yet.">
            <i />{online ? 'Rule-based · verified actions only' : 'Offline'}
          </span>
        </div>
        {chat.length > 0 && <button className="cx-ghost" onClick={clearChat} title="Start a new conversation">New chat</button>}
        <button className="cx-x" onClick={toggleAi} aria-label="Close assistant">×</button>
      </header>

      <div className="cx-body">
        {chat.length === 0 && !aiDraft ? (
          <div className="cx-empty">
            <span className="cx-bigorb"><Sparkle size={30} /></span>
            <h2>What would you like to explore?</h2>
            <p>Ask me to analyze an area, plan a route or a mission, or explain the science. I run the same checked actions as the buttons and only report what the analysis actually returns.</p>
            <div className="cx-cards">
              {SUGGESTIONS.map((c) => (
                <button key={c.title} className="cx-card" onClick={() => sendChat(c.q)}>
                  <span className="cx-ic">{c.icon}</span><b>{c.title}</b><small>{c.desc}</small>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="cx-thread">
            {chat.map((m, i) => (
              <div key={i} className="cx-turn">
                {m.u && <div className="cx-user"><div>{m.u}</div></div>}
                <div className="cx-bot">
                  <span className="cx-av"><Sparkle size={13} /></span>
                  <div className="cx-bot-c">
                    {m.steps && m.steps.length > 0 && <div className="cx-steps">{m.steps.map((s) => <span key={s}><i>✓</i>{s}</span>)}</div>}
                    <p className={m.err ? 'cx-err' : undefined}>{m.r}</p>
                    {m.card && <Card card={m.card} />}
                    {m.note && <div className="cx-note">{m.note}</div>}
                    {m.actions && m.actions.length > 0 && <Actions actions={m.actions} />}
                  </div>
                </div>
              </div>
            ))}
            <JobCard />
            <div ref={endRef} />
          </div>
        )}
      </div>

      <footer className="cx-foot">
        {chat.length > 0 && (
          <div className="cx-quick">
            {['Avoid slopes above 10 degrees', 'Why are hydrated minerals important?'].map((q) => <button key={q} onClick={() => sendChat(q)}>{q}</button>)}
          </div>
        )}
        <div className="cx-composer">
          <textarea ref={boxRef} rows={1} value={aiDraft} placeholder="Ask about this area, a route or the science…" aria-label="Message the assistant"
            onChange={(e) => setAiDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <button className="cx-send" onClick={send} disabled={!aiDraft.trim()} aria-label="Send"><svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 19V5m0 0l-6 6m6-6l6 6" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg></button>
        </div>
        <small className="cx-hint">Answers come from checked tools and real analysis data. Missing data is never filled in. Enter to send · Shift+Enter for a new line</small>
      </footer>
    </aside>
  );
}
