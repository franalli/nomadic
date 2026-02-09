/**
 * Specialist utility functions for contextual UI elements.
 * Used to generate dynamic headers based on active specialists.
 */

import { SPECIALIST_IDS } from '@/lib/specialists';
import type { StrategySection } from '@/types/plan-envelope';

/**
 * Extract active specialist types from strategy sections.
 * Returns only niche specialists (those in the registry), excluding structural roles.
 */
export function getActiveSpecialists(
  sections: StrategySection[] | undefined
): string[] {
  if (!sections) return [];
  return sections
    .map((s) => s.specialist_type)
    .filter(
      (t): t is string =>
        t !== undefined && SPECIALIST_IDS.includes(t)
    );
}

/**
 * Format specialist list for display.
 * @example "diving + hiking" or "diving" or empty string
 */
function formatSpecialistPhrase(specialists: string[]): string {
  if (specialists.length === 0) return '';
  if (specialists.length === 1) return specialists[0];
  return specialists.join(' + ');
}

/**
 * Capitalize the first letter of each word in a phrase.
 */
function capitalizePhrase(phrase: string): string {
  return phrase
    .split(' ')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Generate contextual header for tile category.
 * Returns title and subtitle based on active specialists.
 */
export function generateTileHeader(
  category: 'stays' | 'flights' | 'activities',
  specialists: string[]
): { title: string; subtitle: string } {
  const phrase = formatSpecialistPhrase(specialists);
  const hasSpecialists = phrase.length > 0;
  const capitalizedPhrase = capitalizePhrase(phrase);

  const categoryLabels = {
    stays: {
      title: 'Stays',
      subtitle: hasSpecialists
        ? `Matching ${phrase} constraints`
        : 'Based on your trip preferences',
    },
    flights: {
      title: 'Flights',
      subtitle: hasSpecialists
        ? `Matching ${phrase} constraints`
        : 'Based on your travel dates',
    },
    activities: {
      title: hasSpecialists
        ? `${capitalizedPhrase} Experiences`
        : 'Suggested Activities',
      subtitle: hasSpecialists
        ? `Curated ${phrase} adventures`
        : 'Popular experiences at your destination',
    },
  };

  return categoryLabels[category];
}
