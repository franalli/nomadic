import { format } from 'date-fns';

export function cn(...inputs: Array<string | false | null | undefined>) {
  return inputs.filter(Boolean).join(' ');
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
export const parseBudgetNumber = (budget?: string | number | null): number | null => {
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
export const normalizeBudgetInput = (budget?: string | number | null): string | null => {
  if (budget === null || budget === undefined) return null;
  const text = typeof budget === 'number' ? budget.toString() : budget;
  const trimmed = text.trim();
  return trimmed || null;
};

/**
 * Format a budget value for display (e.g., "$3,000").
 * Returns the numeric formatted value if parseable, otherwise the normalized string.
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  CAD: 'CA$',
  AUD: 'A$',
  JPY: '¥',
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

/**
 * Format a budget value for form display. Returns empty string if null/undefined.
 * Always returns a string (never null).
 */
export const formatBudgetValue = (value?: string | number | null): string => {
  if (value === null || value === undefined) return '';
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return '';
  return `$${Math.round(parsed).toLocaleString()}`;
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
 * Normalize an activity string to ensure it has an emoji prefix.
 *
 * - If the activity already starts with an emoji, return it as-is
 * - Otherwise, look up the activity in the emoji map and add the appropriate emoji
 * - If no match found, use the sparkle emoji as default
 */
export const normalizeActivityWithEmoji = (activity: string): string => {
  const trimmed = activity.trim();
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

  // Try partial matching - check if any keyword is contained in the activity
  for (const [keyword, emoji] of Object.entries(ACTIVITY_EMOJI_MAP)) {
    // Only match if keyword is a complete word in the activity
    const regex = new RegExp(`\\b${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    if (regex.test(activityLower)) {
      return `${emoji} ${trimmed}`;
    }
  }

  // No match found, use default sparkle emoji
  return `${DEFAULT_ACTIVITY_EMOJI} ${trimmed}`;
};

/**
 * Extract the text portion of an activity string (after the emoji).
 */
const getActivityTextPortion = (activity: string): string => {
  const text = activity.trim();
  // Find where the actual text starts (after emoji and space)
  for (let i = 0; i < text.length; i++) {
    const codePoint = text.codePointAt(i) ?? 0;
    if (codePoint < 0x1f00 && text[i] !== ' ') {
      return text.slice(i).trim().toLowerCase();
    } else if (text[i] === ' ' && i > 0) {
      return text.slice(i + 1).trim().toLowerCase();
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
