/**
 * specialistLinkParser
 *
 * Preprocesses chat message content to make specialist mentions clickable.
 * Detects patterns like "**Diving Specialist** applied..." and converts
 * them to deep links that navigate to the Plan tab and scroll to the card.
 */

import { SPECIALIST_DISPLAY_NAMES, getSpecialistConfig } from './specialists';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type SpecialistType = string;

// ─────────────────────────────────────────────────────────────────────────────
// Patterns (generated from registry)
// ─────────────────────────────────────────────────────────────────────────────

const ALL_DISPLAY_NAMES = Object.values(SPECIALIST_DISPLAY_NAMES);
const NAME_ALTERNATION = ALL_DISPLAY_NAMES.join('|');

const SPECIALIST_PATTERNS = [
  new RegExp(`\\*\\*(${NAME_ALTERNATION})\\s+Specialist\\*\\*`, 'gi'),
  new RegExp(`(?<!\\*\\*)(${NAME_ALTERNATION})\\s+Specialist(?!\\*\\*)`, 'gi'),
];

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Normalize specialist name to type string.
 * e.g., "Local Expert" -> "local_expert", "Diving" -> "diving"
 */
export function normalizeSpecialistType(name: string): SpecialistType {
  return name.toLowerCase().replace(/\s+/g, '_') as SpecialistType;
}

/**
 * Check if a string contains specialist mentions.
 */
export function hasSpecialistMentions(content: string): boolean {
  return SPECIALIST_PATTERNS.some((pattern) => {
    // Reset lastIndex for global regex
    pattern.lastIndex = 0;
    return pattern.test(content);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Functions
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Preprocess message content to convert specialist mentions to deep links.
 *
 * Converts patterns like:
 *   "**Diving Specialist** applied 24h buffer"
 * To:
 *   "[**Diving Specialist**](specialist:diving) applied 24h buffer"
 *
 * The `specialist:` protocol is then handled by a custom link renderer
 * in the chat markdown component.
 */
export function preprocessSpecialistLinks(content: string): string {
  let result = content;

  for (const pattern of SPECIALIST_PATTERNS) {
    // Reset lastIndex for global regex
    pattern.lastIndex = 0;

    result = result.replace(pattern, (match, specialistName: string) => {
      const normalizedType = normalizeSpecialistType(specialistName);
      // Preserve the original formatting (bold or not)
      return `[${match}](specialist:${normalizedType})`;
    });
  }

  return result;
}

/**
 * Extract specialist type from a specialist: protocol URL.
 * e.g., "specialist:diving" -> "diving"
 */
export function parseSpecialistLink(href: string): SpecialistType | null {
  if (!href.startsWith('specialist:')) {
    return null;
  }
  const type = href.replace('specialist:', '') as SpecialistType;
  return type;
}

/**
 * Get display name for a specialist type.
 * e.g., "diving" -> "Diving Specialist", "local_expert" -> "Local Expert Specialist"
 */
export function getSpecialistDisplayName(type: SpecialistType): string {
  const config = getSpecialistConfig(type);
  if (config) return `${config.displayName} Specialist`;
  const displayName = SPECIALIST_DISPLAY_NAMES[type];
  if (displayName) return `${displayName} Specialist`;
  return `${type} Specialist`;
}
