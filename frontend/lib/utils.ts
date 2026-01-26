import { format } from 'date-fns';

type ClassValue = string | false | null | undefined | (string | false | null | undefined)[];

export function cn(...inputs: ClassValue[]): string {
  return inputs.flat().filter(Boolean).join(' ');
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile Type Detection Utilities
// ─────────────────────────────────────────────────────────────────────────────

const FLIGHT_TYPE_KEYWORDS = ['flight', 'air', 'fare', 'plane'] as const;
const ACTIVITY_TYPE_KEYWORDS = ['activity', 'experience', 'tour', 'excursion', 'ticket', 'event'] as const;

/**
 * Check if a tile type string represents a flight.
 */
export const isFlightType = (type: string): boolean => {
  const lower = type.toLowerCase();
  return FLIGHT_TYPE_KEYWORDS.some((keyword) => lower.includes(keyword));
};

/**
 * Check if a tile type string represents an activity.
 */
export const isActivityType = (type: string): boolean => {
  const lower = type.toLowerCase();
  return ACTIVITY_TYPE_KEYWORDS.some((keyword) => lower.includes(keyword));
};

// ─────────────────────────────────────────────────────────────────────────────
// Date Formatting Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format an ISO date string (YYYY-MM-DD) for display.
 * Returns a human-readable format like "Wed, Dec 15".
 */
export const formatDateForDisplay = (value?: string | null): string => {
  if (!value) return '';
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (isoMatch) {
    try {
      const date = new Date(value + 'T00:00:00');
      return format(date, 'MMM d');
    } catch {
      return value;
    }
  }
  return value;
};

// ─────────────────────────────────────────────────────────────────────────────
// Budget Formatting Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parse a budget value to a number. Returns null if invalid or non-positive.
 */
const parseBudgetNumber = (budget?: string | number | null): number | null => {
  if (budget === null || budget === undefined) return null;
  const text = typeof budget === 'number' ? budget.toString() : budget;
  const cleaned = text.replace(/[^0-9.]/g, '');
  const parsed = parseFloat(cleaned);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.round(parsed);
};

/**
 * Normalize a budget input to a trimmed string or null.
 */
const normalizeBudgetInput = (budget?: string | number | null): string | null => {
  if (budget === null || budget === undefined) return null;
  const text = typeof budget === 'number' ? budget.toString() : budget;
  const trimmed = text.trim();
  return trimmed || null;
};

/**
 * Format a budget value for display (e.g., "$3,000").
 * Returns the numeric formatted value if parseable, otherwise the normalized string.
 * Currency symbols synced with backend CURRENCY_SYMBOL_MAP in graph_plan_utils.py
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  CAD: 'CA$',
  AUD: 'A$',
  JPY: '¥',
  CHF: 'CHF',
  CNY: '¥',
  INR: '₹',
  KRW: '₩',
  MXN: 'MX$',
  NZD: 'NZ$',
  SEK: 'kr',
  SGD: 'S$',
  HKD: 'HK$',
  BRL: 'R$',
};

export const formatBudgetDisplay = (
  budget?: string | number | null,
  currency?: string | null
): string | null => {
  const numeric = parseBudgetNumber(budget);
  const symbol = currency ? CURRENCY_SYMBOLS[currency] ?? currency : null;

  if (numeric) {
    if (symbol) {
      const prefixSymbols = ['$', '€', '£', '¥'];
      const usePrefix = prefixSymbols.some((s) => symbol.startsWith(s));
      return usePrefix ? `${symbol}${numeric.toLocaleString()}` : `${numeric.toLocaleString()} ${symbol}`;
    }
    return `$${numeric.toLocaleString()}`;
  }
  const normalized = normalizeBudgetInput(budget);
  if (normalized && symbol) return `${normalized} ${symbol}`;
  return normalized;
};

// ─────────────────────────────────────────────────────────────────────────────
// Activity Emoji Normalization Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Maps activity keywords (lowercase) to their emoji prefixes.
 * Used to normalize activities so they all have consistent emoji prefixes.
 */
const ACTIVITY_EMOJI_MAP: Record<string, string> = {
  // Beach/coastal
  beach: '🏖️',
  coastal: '🏖️',
  seaside: '🏖️',
  // Romantic
  romantic: '💕',
  couples: '💕',
  honeymoon: '💕',
  // Adventure/extreme
  adventure: '🧗',
  extreme: '🧗',
  adrenaline: '🧗',
  climbing: '🧗',
  'rock climbing': '🧗',
  bungee: '🧗',
  skydiving: '🧗',
  paragliding: '🧗',
  'zip-line': '🧗',
  zipline: '🧗',
  // Family
  family: '👨‍👩‍👧',
  kids: '👨‍👩‍👧',
  children: '👨‍👩‍👧',
  // Food/culinary
  food: '🍝',
  culinary: '🍝',
  gastronomy: '🍝',
  'food tour': '🍝',
  'cooking class': '🍝',
  'street food': '🍝',
  // Wine/tasting
  wine: '🍷',
  vineyard: '🍷',
  tasting: '🍷',
  'wine tasting': '🍷',
  brewery: '🍷',
  distillery: '🍷',
  // Culture/museums
  culture: '🏛️',
  museums: '🏛️',
  galleries: '🏛️',
  art: '🏛️',
  exhibitions: '🏛️',
  sightseeing: '🏛️',
  // History
  history: '📜',
  heritage: '📜',
  ancient: '📜',
  archaeology: '📜',
  // Theater/shows
  theater: '🎭',
  theatre: '🎭',
  shows: '🎭',
  opera: '🎭',
  ballet: '🎭',
  broadway: '🎭',
  cabaret: '🎭',
  comedy: '🎭',
  // Spa/wellness
  spa: '💆',
  wellness: '💆',
  yoga: '💆',
  meditation: '💆',
  retreat: '💆',
  'spa day': '💆',
  massage: '💆',
  // Relaxation
  relaxation: '😌',
  chill: '😌',
  unwind: '😌',
  // Hiking/trekking
  hiking: '🥾',
  trekking: '🥾',
  trails: '🥾',
  hike: '🥾',
  trek: '🥾',
  // Dirt riding/motorbike
  'dirt riding': '🏍️',
  motorbike: '🏍️',
  atv: '🏍️',
  quad: '🏍️',
  'off-road': '🏍️',
  motocross: '🏍️',
  motogp: '🏍️',
  // Racing/F1
  f1: '🏎️',
  racing: '🏎️',
  motorsport: '🏎️',
  'go-kart': '🏎️',
  'formula 1': '🏎️',
  'grand prix': '🏎️',
  nascar: '🏎️',
  // Diving/snorkeling
  diving: '🤿',
  snorkeling: '🤿',
  scuba: '🤿',
  // Skiing/winter
  skiing: '⛷️',
  snowboarding: '⛷️',
  'winter sports': '⛷️',
  'snow activities': '🎿',
  // Nightlife
  nightlife: '🎉',
  clubs: '🎉',
  bars: '🎉',
  entertainment: '🎉',
  party: '🎉',
  clubbing: '🎉',
  'night out': '🎉',
  // Running
  running: '🏃',
  jogging: '🏃',
  marathon: '🏃',
  triathlon: '🏃',
  'trail running': '🏃',
  // Backpacking
  backpacking: '🎒',
  'budget travel': '🎒',
  // Music
  music: '🎵',
  concerts: '🎵',
  festivals: '🎵',
  'live music': '🎵',
  dj: '🎵',
  rave: '🎵',
  // Movies/film
  movies: '🎬',
  film: '🎬',
  'film festival': '🎬',
  premiere: '🎬',
  cinema: '🎬',
  'celebrity events': '🎬',
  // Circus/carnival
  circus: '🎪',
  carnival: '🎪',
  parade: '🎪',
  celebration: '🎪',
  fair: '🎪',
  // Shopping
  shopping: '🛍️',
  markets: '🛍️',
  boutiques: '🛍️',
  // Cycling
  cycling: '🚴',
  biking: '🚴',
  'mountain biking': '🚴',
  bmx: '🚴',
  // Surfing/water sports
  surfing: '🏄',
  'water sports': '🏄',
  'jet ski': '🏄',
  wakeboard: '🏄',
  // Kayaking/paddling
  kayaking: '🛶',
  canoeing: '🛶',
  paddleboarding: '🛶',
  rafting: '🛶',
  // Sailing/boating
  sailing: '⛵',
  boating: '⛵',
  yacht: '⛵',
  cruise: '⛵',
  // Fishing
  fishing: '🎣',
  'deep sea fishing': '🎣',
  // Safari/wildlife
  safari: '🦁',
  wildlife: '🦁',
  'animal watching': '🦁',
  zoo: '🦁',
  'whale watching': '🦁',
  'wildlife tours': '🦁',
  // Nature
  nature: '🌲',
  'national parks': '🌲',
  aurora: '🌲',
  'northern lights': '🌲',
  outdoor: '🌲',
  'outdoor activities': '🌲',
  // Golf
  golf: '⛳',
  // Tennis
  tennis: '🎾',
  // Sports events
  basketball: '🏀',
  football: '🏀',
  soccer: '🏀',
  'sports events': '🏀',
  // Academic
  academic: '🎓',
  conference: '🎓',
  seminar: '🎓',
  workshop: '🎓',
  lecture: '🎓',
  university: '🎓',
  research: '🎓',
  'study abroad': '🎓',
  // Competition
  competition: '🏆',
  hackathon: '🏆',
  tournament: '🏆',
  championship: '🏆',
  esports: '🏆',
  olympics: '🏆',
  'world cup': '🏆',
  // Tours (generic)
  tours: '🎫',
  'guided tours': '🎫',
  excursions: '🎫',
  'day trips': '🎫',
  // Experiences
  experiences: '🌟',
  'local experiences': '🌟',
};

/** Default emoji for activities that don't match any known category */
const DEFAULT_ACTIVITY_EMOJI = '✨';

/**
 * Check if a string starts with an emoji character.
 */
const startsWithEmoji = (str: string): boolean => {
  if (!str || str.length === 0) return false;
  const codePoint = str.codePointAt(0) ?? 0;
  // Emoji ranges (simplified check)
  return codePoint > 0x1f00;
};

/**
 * Strip ANSI escape codes and control characters from a string.
 */
const stripControlChars = (text: string): string => {
  // Remove ANSI escape sequences (ESC[ and CSI)

  const withoutAnsi = text.replace(/(\x1b|\x9b)\[[0-9;:]*[A-Za-z]/g, '');
  // Remove non-printable control characters (except space, tab, newline)

  return withoutAnsi.replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]/g, '');
};

/**
 * Normalize an activity string to ensure it has an emoji prefix.
 *
 * - Strips ANSI escape codes and control characters
 * - Applies NFC Unicode normalization to fix decomposed emoji codepoints
 * - If the activity already starts with an emoji, return it as-is
 * - Otherwise, look up the activity in the emoji map and add the appropriate emoji
 * - If no match found, use the sparkle emoji as default
 */
export const normalizeActivityWithEmoji = (activity: string): string => {
  // Strip control characters and normalize Unicode
  const sanitized = stripControlChars(activity).normalize('NFC');
  const trimmed = sanitized.trim();
  if (!trimmed) return trimmed;

  // Check if already has emoji prefix
  if (startsWithEmoji(trimmed)) {
    return trimmed;
  }

  const activityLower = trimmed.toLowerCase();

  // Direct match in emoji map
  if (activityLower in ACTIVITY_EMOJI_MAP) {
    const emoji = ACTIVITY_EMOJI_MAP[activityLower];
    return `${emoji} ${trimmed}`;
  }

  // Try matching with common suffixes removed
  for (const suffix of [' activities', ' tours', ' experiences']) {
    if (activityLower.endsWith(suffix)) {
      const base = activityLower.slice(0, -suffix.length);
      if (base in ACTIVITY_EMOJI_MAP) {
        const emoji = ACTIVITY_EMOJI_MAP[base];
        return `${emoji} ${trimmed}`;
      }
    }
  }

  // Try partial matching - prioritize earliest position and longest keyword
  let bestMatch: { pos: number; length: number; emoji: string } | null = null;
  for (const [keyword, emoji] of Object.entries(ACTIVITY_EMOJI_MAP)) {
    const regex = new RegExp(`\\b${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    const match = regex.exec(activityLower);
    if (match) {
      const pos = match.index;
      const length = keyword.length;
      // Earlier position wins, then longer keyword wins
      if (!bestMatch || pos < bestMatch.pos || (pos === bestMatch.pos && length > bestMatch.length)) {
        bestMatch = { pos, length, emoji };
      }
    }
  }

  if (bestMatch) {
    return `${bestMatch.emoji} ${trimmed}`;
  }

  // No match found, use default sparkle emoji
  return `${DEFAULT_ACTIVITY_EMOJI} ${trimmed}`;
};

/**
 * Extract the text portion of an activity string (after the emoji).
 * Uses Intl.Segmenter for proper grapheme cluster handling of multi-codepoint emojis.
 */
const getActivityTextPortion = (activity: string): string => {
  const text = activity.trim();
  if (!text) return '';

  // Check if first character is in emoji range
  const firstCodePoint = text.codePointAt(0) ?? 0;
  if (firstCodePoint > 0x1f00) {
    // Use Intl.Segmenter for proper grapheme handling (handles ZWJ sequences, variation selectors, etc.)
    const segmenter = new Intl.Segmenter('en', { granularity: 'grapheme' });
    const segments = [...segmenter.segment(text)];
    if (segments.length > 1) {
      // Skip the first grapheme (emoji) and return the rest
      return segments
        .slice(1)
        .map((s) => s.segment)
        .join('')
        .trim()
        .toLowerCase();
    }
  }
  return text.toLowerCase();
};

/**
 * Check if two activities are duplicates (case-insensitive, ignoring emoji prefix).
 */
export const areActivitiesDuplicate = (activity1: string, activity2: string): boolean => {
  const text1 = getActivityTextPortion(activity1);
  const text2 = getActivityTextPortion(activity2);
  return text1 === text2;
};

/**
 * Deduplicate activity categories case-insensitively.
 * When comparing, strips the emoji prefix to compare only the activity text.
 * Keeps the first occurrence of each unique activity.
 */
export const deduplicateActivities = (categories: string[]): string[] => {
  const seen = new Set<string>();
  const deduped: string[] = [];

  for (const cat of categories) {
    const textPortion = getActivityTextPortion(cat);
    if (textPortion && !seen.has(textPortion)) {
      seen.add(textPortion);
      deduped.push(cat);
    }
  }

  return deduped;
};
