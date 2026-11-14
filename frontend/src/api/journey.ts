// Understanding a "science journey" request typed in the chat: an objective, an oxygen budget and a mission/journey intent.
// Pure functions: the chat flow that acts on them lives in the dashboard store.
import type { Pt, Region } from '../types/ui';
import { KM_PER_PX } from '../utils/geo';
import { matchObjective } from './objectives';
import type { ObjectiveInfo } from './objectives';

export interface Journey {
  /** The message asks for a mission/journey (and not for a route, an analysis or a slope setting). */
  intent: boolean;
  oxygenH: number | null;
  objective: ObjectiveInfo | null;
  /** No supported objective was named, but the message states a science goal worth checking against NASA's catalog. */
  statesGoal: boolean;
}

const WORDS: Record<string, number> = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, twelve: 12 };
const INTENT = /\b(plan|find|mission|journey|expedition|explore|oxygen|hours?|traverse|science)\b/;
const COMMAND = /\b(analy[sz]e|slopes?|routes?|safest)\b/;
const GOAL = /\b(find|study|look(?:ing)? for|search(?:ing)? for|investigate|formations?|thermal|boxwork|dunes?|ice|volcan\w*|sediment\w*|geolog\w*|radiation|water|methane|salts?|sulfates?|carbonates?|craters?)\b/;

/** Oxygen hours from phrases like "4 hours", "3.5 h", "four hours of oxygen"; null when none is stated. */
export function parseOxygenHours(text: string): number | null {
  const t = text.toLowerCase().replace(/\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve)\b/g, (m) => String(WORDS[m]));
  const m = t.match(/(\d+(?:\.\d+)?)\s*-?\s*(?:h|hr|hrs|hour|hours)\b/);
  const hours = m ? Number(m[1]) : NaN;
  return Number.isFinite(hours) && hours > 0 && hours <= 48 ? hours : null;
}

export function parseJourney(text: string, objectives: ObjectiveInfo[]): Journey {
  const t = text.toLowerCase();
  const intent = INTENT.test(t) && !COMMAND.test(t);
  const objective = intent ? matchObjective(t, objectives) : null;
  return { intent, oxygenH: parseOxygenHours(t), objective, statesGoal: intent && !objective && GOAL.test(t) };
}

/**
 * The square around the base that an oxygen budget can plausibly reach: half the walking pace (2 km/h) times the hours
 * gives the radius, never under 6 km (a useful analysis) and never over 22 km (an analysis is at most about 45 km across).
 */
export function journeyRegion(base: Pt, hours: number): Region {
  const half = Math.min(22, Math.max(6, hours));
  const px = Math.round((2 * half) / KM_PER_PX);
  return { x: Math.round(base.x - px / 2), y: Math.round(base.y - px / 2), w: px, h: px };
}
