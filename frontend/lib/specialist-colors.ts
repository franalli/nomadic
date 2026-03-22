/**
 * Specialist-to-color mappings for UI labels and badges.
 *
 * SSoT for specialist text colors used in DragPreviewCard and ActivityMiniCard.
 * Hue assignments match the DS constraint-priority palette.
 * Derived from SPECIALIST_REGISTRY in specialists.ts to avoid SSoT fragmentation.
 */

import { getSpecialistColor, SPECIALIST_IDS } from './specialists';

/** Hex color to Tailwind text class mapping (dark mode pair).
 *  Diving (#0EA5E9 sky-500) uses text-sky to distinguish from Sailing (#06B6D4 cyan-500). */
const HEX_TO_TEXT_CLASS: Record<string, string> = {
  '#0EA5E9': 'text-sky-600 dark:text-sky-400',
  '#10B981': 'text-emerald-600 dark:text-emerald-400',
  '#3B82F6': 'text-blue-600 dark:text-blue-400',
  '#84CC16': 'text-lime-600 dark:text-lime-400',
  '#6366F1': 'text-indigo-600 dark:text-indigo-400',
  '#F97316': 'text-orange-600 dark:text-orange-400',
  '#06B6D4': 'text-cyan-600 dark:text-cyan-400',
  '#D97706': 'text-amber-600 dark:text-amber-400',
};

const DEFAULT_TEXT_CLASS = 'text-emerald-600 dark:text-emerald-400';

/** Text color classes for specialist labels (e.g., "Diving" badge text).
 *  Derived from SPECIALIST_REGISTRY — adding a specialist there auto-populates this map. */
export const SPECIALIST_TEXT_COLOR: Record<string, string> = {
  ...Object.fromEntries(
    SPECIALIST_IDS.map((id) => [id, HEX_TO_TEXT_CLASS[getSpecialistColor(id)] ?? DEFAULT_TEXT_CLASS]),
  ),
  boating: HEX_TO_TEXT_CLASS[getSpecialistColor('sailing')] ?? DEFAULT_TEXT_CLASS,
};
