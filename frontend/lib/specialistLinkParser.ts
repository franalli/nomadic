/**
 * specialistLinkParser
 *
 * Preprocesses chat message content to make specialist mentions clickable.
 * Detects patterns like "**Diving Specialist** applied..." and converts
 * them to deep links that navigate to the Plan tab and scroll to the card.
 */

import { SPECIALIST_DISPLAY_NAMES } from './specialists';

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
function normalizeSpecialistType(name: string): SpecialistType {
  return name.toLowerCase().replace(/\s+/g, '_') as SpecialistType;
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
