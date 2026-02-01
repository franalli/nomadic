/**
 * Specialist utility functions for contextual UI elements.
 * Used to generate dynamic headers based on active specialists.
 */

import type { StrategySection } from '@/types/plan-envelope';

/**
 * Extract active specialist types from strategy sections.
 * Excludes 'general' and 'local_expert' which are always present.
 */
export function getActiveSpecialists(
  sections: StrategySection[] | undefined
): string[] {
  if (!sections) return [];
  return sections
    .map((s) => s.specialist_type)
    .filter(
      (t): t is string =>
        t !== undefined && t !== 'general' && t !== 'local_expert'
    );
}

/**
 * Format specialist list for display.
 * @example "diving + hiking" or "diving" or empty string
 */
export function formatSpecialistPhrase(specialists: string[]): string {
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
      title: hasSpecialists
        ? `Suggested Accommodations for your ${phrase} adventure`
        : 'Suggested Accommodations',
      subtitle: hasSpecialists
        ? `Based on your ${phrase} activities`
        : 'Based on your trip preferences',
    },
    flights: {
      title: 'Flight Options',
      subtitle: hasSpecialists
        ? `Timed for your ${phrase} schedule`
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
