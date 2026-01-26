/**
 * specialistLinkParser
 *
 * Preprocesses chat message content to make specialist mentions clickable.
 * Detects patterns like "**Diving Specialist** applied..." and converts
 * them to deep links that navigate to the Plan tab and scroll to the card.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type SpecialistType =
  | 'diving'
  | 'hiking'
  | 'skiing'
  | 'cycling'
  | 'boating'
  | 'local_expert'
  | 'general';

// ─────────────────────────────────────────────────────────────────────────────
// Patterns
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Patterns to detect specialist mentions in chat content.
 * Matches both bold (**) and non-bold mentions.
 */
const SPECIALIST_PATTERNS = [
  // Bold mentions: **Diving Specialist**
  /\*\*(Diving|Hiking|Skiing|Cycling|Boating|Local Expert|General)\s+Specialist\*\*/gi,
  // Plain mentions: Diving Specialist (not as common but supported)
  /(?<!\*\*)(Diving|Hiking|Skiing|Cycling|Boating|Local Expert|General)\s+Specialist(?!\*\*)/gi,
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
  const nameMap: Record<SpecialistType, string> = {
    diving: 'Diving Specialist',
    hiking: 'Hiking Specialist',
    skiing: 'Skiing Specialist',
    cycling: 'Cycling Specialist',
    boating: 'Boating Specialist',
    local_expert: 'Local Expert Specialist',
    general: 'General Specialist',
  };
  return nameMap[type] || `${type} Specialist`;
}
