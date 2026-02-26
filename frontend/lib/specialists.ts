/**
 * Specialist Registry — Single Source of Truth (Frontend)
 *
 * All frontend specialist data lives here. Adding a specialist = adding one entry.
 * Components import colors, icons, keywords, and helpers from this file.
 *
 * Must mirror backend specialist_registry.py — sync manually until API endpoint exists.
 */

// ---------------------------------------------------------------------------
// Config type
// ---------------------------------------------------------------------------

export interface SpecialistConfig {
  id: string;
  displayName: string;
  icon: string; // Lucide icon name
  emoji: string;
  color: string; // Hex — use inline styles, not Tailwind
  filterKeywords: string[];
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

const SPECIALIST_REGISTRY: Record<string, SpecialistConfig> = {
  diving: {
    id: 'diving',
    displayName: 'Diving',
    icon: 'Waves',
    emoji: '🤿',
    color: '#0EA5E9',
    filterKeywords: ['div', 'scuba', 'snorkel', 'reef', 'underwater', 'wreck'],
  },
  hiking: {
    id: 'hiking',
    displayName: 'Hiking',
    icon: 'Mountain',
    emoji: '🥾',
    color: '#10B981',
    filterKeywords: ['hik', 'trek', 'trail', 'climb', 'summit', 'mountain'],
  },
  skiing: {
    id: 'skiing',
    displayName: 'Skiing',
    icon: 'Snowflake',
    emoji: '⛷️',
    color: '#3B82F6',
    filterKeywords: ['ski', 'snow', 'slope', 'piste', 'powder', 'chairlift', 'gondola'],
  },
  cycling: {
    id: 'cycling',
    displayName: 'Cycling',
    icon: 'Bike',
    emoji: '🚴',
    color: '#84CC16',
    filterKeywords: ['cycl', 'bike', 'biking', 'pedal', 'mtb'],
  },
  surfing: {
    id: 'surfing',
    displayName: 'Surfing',
    icon: 'Waves',
    emoji: '🏄',
    color: '#6366F1',
    filterKeywords: ['surf', 'wave', 'board', 'swell'],
  },
  climbing: {
    id: 'climbing',
    displayName: 'Climbing',
    icon: 'Mountain',
    emoji: '🧗',
    color: '#F97316',
    filterKeywords: ['climb', 'boulder', 'crag', 'via ferrata', 'rope', 'ascent'],
  },
  sailing: {
    id: 'sailing',
    displayName: 'Sailing',
    icon: 'Sailboat',
    emoji: '⛵',
    color: '#06B6D4',
    filterKeywords: ['sail', 'yacht', 'charter', 'catamaran', 'marina', 'regatta'],
  },
  wildlife_safari: {
    id: 'wildlife_safari',
    displayName: 'Wildlife Safari',
    icon: 'Binoculars',
    emoji: '🦁',
    color: '#D97706',
    filterKeywords: ['safari', 'wildlife', 'game drive', 'big five', 'savanna'],
  },
};

// ---------------------------------------------------------------------------
// Derived constants
// ---------------------------------------------------------------------------

/** All specialist IDs */
export const SPECIALIST_IDS = Object.keys(SPECIALIST_REGISTRY);

/** Color lookup with backward-compat aliases */
const SPECIALIST_COLORS: Record<string, string> = {
  local_expert: '#6B7280',
  general: '#6B7280',
  ...Object.fromEntries(SPECIALIST_IDS.map((id) => [id, SPECIALIST_REGISTRY[id].color])),
  boating: SPECIALIST_REGISTRY.sailing.color,
  default: '#71717A',
};

/** Display name lookup for regex generation in link parser */
export const SPECIALIST_DISPLAY_NAMES: Record<string, string> = {
  ...Object.fromEntries(SPECIALIST_IDS.map((id) => [id, SPECIALIST_REGISTRY[id].displayName])),
  local_expert: 'Local Expert',
  general: 'General',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getSpecialistColor(type?: string): string {
  return SPECIALIST_COLORS[type || ''] || SPECIALIST_COLORS.default;
}

/** Convert specialist hex color to RGB triplet string for CSS custom property usage */
export function getSpecialistColorRgb(type?: string): string {
  const hex = getSpecialistColor(type);
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `${r} ${g} ${b}`;
}

export function getSpecialistConfig(type?: string): SpecialistConfig | undefined {
  if (!type) return undefined;
  if (type === 'boating') return SPECIALIST_REGISTRY.sailing;
  return SPECIALIST_REGISTRY[type];
}

/** Activity tile matches any of the given specialist types? */
export function activityMatchesSpecialist(
  tile: { category?: string; type?: string; title?: string },
  specialistTypes: string[],
): boolean {
  if (!specialistTypes || specialistTypes.length === 0) return true;

  const category = (tile.category || tile.type || '').toLowerCase();
  const title = (tile.title || '').toLowerCase();

  for (const specialist of specialistTypes) {
    if (specialist === 'local_expert') return true;
    const config = getSpecialistConfig(specialist);
    if (!config) continue;
    for (const kw of config.filterKeywords) {
      if (category.includes(kw) || title.includes(kw)) return true;
    }
  }
  return false;
}
