/**
 * ActivitiesSheetParts
 *
 * Extracted normalization, initial-value derivation helpers, and sub-components
 * for ActivitiesSheet.
 */

import { canonicalCategoryKey } from '@/lib/categoryNormalization';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { ActivitySettings } from '@/types/document';

/**
 * Normalize raw category strings to canonical keys, deduplicating.
 */
export function normalizeSettingCategories(categories: string[] | undefined | null): string[] {
  return Array.from(
    new Set(
      (categories ?? [])
        .map((category) => canonicalCategoryKey(category))
        .filter((category): category is string => !!category)
    )
  );
}

/**
 * Normalize day_preferences keys to canonical category keys,
 * rounding values and filtering invalid entries.
 */
export function normalizeSettingDayPreferences(
  dayPreferences: Record<string, number> | undefined | null
): Record<string, number> {
  const normalizedEntries: Array<[string, number]> = [];
  Object.entries(dayPreferences ?? {}).forEach(([rawCategory, rawDays]) => {
    const category = canonicalCategoryKey(rawCategory);
    if (!category || typeof rawDays !== 'number' || !Number.isFinite(rawDays)) return;
    normalizedEntries.push([category, Math.max(0, Math.round(rawDays))]);
  });
  return Object.fromEntries(normalizedEntries);
}

/**
 * Derive the effective initial categories to show when the sheet opens.
 * If saved categories exist, use them. Otherwise, if the user never explicitly
 * saved, fall back to inferred categories from day cards.
 */
export function deriveEffectiveInitialCategories(
  normalizedSettingCategories: string[],
  hasExplicitSettings: boolean,
  inferredCategories: string[]
): string[] {
  return normalizedSettingCategories.length > 0
    ? normalizedSettingCategories
    : (hasExplicitSettings ? normalizedSettingCategories : inferredCategories);
}

/**
 * Derive the effective initial day preferences to show when the sheet opens.
 * When an itinerary exists, merge inferred preferences with saved ones for active categories.
 */
export function deriveEffectiveInitialDayPreferences(
  hasItinerary: boolean,
  effectiveInitialCategories: string[],
  inferredDayPreferences: Record<string, number>,
  normalizedDayPrefs: Record<string, number>
): Record<string, number> {
  if (!hasItinerary) return normalizedDayPrefs;
  return Object.fromEntries(
    effectiveInitialCategories
      .map((cat) => [
        cat,
        inferredDayPreferences[cat] ?? normalizedDayPrefs[cat],
      ] as const)
      .filter((entry): entry is [string, number] => entry[1] != null && entry[1] > 0)
  );
}

/**
 * Build the cleaned ActivitySettings payload for save.
 * Only includes day_preferences for categories the user explicitly adjusted.
 */
export function buildSavePayload(
  localCategories: string[],
  localDayPreferences: Record<string, number>,
  localPace: number | null,
  userAdjustedCategories: Set<string>
): ActivitySettings {
  const activeCategorySet = new Set(localCategories);
  const cleanedDayPreferences = Object.fromEntries(
    Object.entries(localDayPreferences).filter(
      ([cat]) => activeCategorySet.has(cat) && userAdjustedCategories.has(cat)
    )
  );
  return {
    categories: localCategories,
    skill_level: null,
    day_preferences: cleanedDayPreferences,
    activities_per_day: localPace,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Footer sub-component
// ─────────────────────────────────────────────────────────────────────────────

interface ActivitiesSheetFooterProps {
  localEnabled: boolean;
  onCancel: () => void;
  onSave: () => void;
}

export function ActivitiesSheetFooter({ localEnabled, onCancel, onSave }: ActivitiesSheetFooterProps) {
  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={onCancel}
        className={cn(
          'flex-1 px-4 py-2.5 rounded-xl text-sm font-medium',
          'text-zinc-500 dark:text-zinc-500',
          'hover:text-zinc-900 hover:bg-zinc-100',
          'dark:hover:text-white dark:hover:bg-white/5',
          'transition-colors'
        )}
      >
        Cancel
      </button>
      <button
        type="button"
        onClick={onSave}
        disabled={!localEnabled}
        className={cn(
          localEnabled ? DS.actions.primary : DS.actions.primaryDisabled,
          'flex-1 px-4 py-2.5 font-semibold'
        )}
      >
        Save
      </button>
    </div>
  );
}
