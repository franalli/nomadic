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
