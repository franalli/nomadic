'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivitiesSheet
 *
 * Module sheet for activity preferences.
 * Prerequisites: Destination (dates optional)
 * Includes toggle + category selection + pace.
 */


import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useToast } from '@/components/ui/toast';
import { canonicalCategoryKey, TIER1_CONSTRAINT_HINTS, toCategoryKey } from '@/lib/categoryNormalization';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { ActivitySettings } from '@/types/document';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { ActivitiesSheetContent, ALL_CATEGORIES } from './ActivitiesSheetContent';
import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface ActivitiesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Module state
  enabled: boolean;
  settings: ActivitySettings;
  /** True when activity_settings has been explicitly saved at least once.
   *  When false, inferred categories from day cards are shown as initial selection. */
  hasExplicitSettings?: boolean;
  // Prerequisites
  hasDestination: boolean;
  // Actions
  onToggle: (enabled: boolean) => void;
  onSaveSettings: (settings: ActivitySettings) => void;
  // Navigate to fix prerequisites
  onOpenDestination?: () => void;
}

const NON_ACTIVITY_TYPES = new Set([
  'arrival', 'departure', 'check-in', 'check-out', 'check_in', 'check_out',
  'free_day', 'rest_day', 'buffer', 'decompression_buffer',
]);

function resolveBlockCategory(block: DayBlock): string | null {
  if (block.is_buffer) return null;
  const activityType = toCategoryKey(block.activity_type);
  if (activityType && NON_ACTIVITY_TYPES.has(activityType)) return null;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : undefined;

  return (
    canonicalCategoryKey(block.map_type) ??
    canonicalCategoryKey(block.specialist_type) ??
    canonicalCategoryKey(bookedTile?.map_type) ??
    canonicalCategoryKey(meta?.map_type) ??
    canonicalCategoryKey((bookedTile as Record<string, unknown> | undefined)?.browse_category) ??
    canonicalCategoryKey(bookedTile?.category) ??
    canonicalCategoryKey(meta?.category)
  );
}

function inferConstraintCategories(block: DayBlock): string[] {
  const categories = new Set<string>();
  const specialist = canonicalCategoryKey(block.specialist_type);
  if (specialist && specialist in TIER1_CONSTRAINT_HINTS) {
    categories.add(specialist);
  }

  const textParts: string[] = [];
  if (typeof block.buffer_reason === 'string') textParts.push(block.buffer_reason);
  if (Array.isArray(block.constraints)) textParts.push(...block.constraints.filter((c): c is string => typeof c === 'string'));
  if (Array.isArray(block.active_constraints)) {
    block.active_constraints.forEach((c) => {
      if (typeof c.id === 'string') textParts.push(c.id);
      if (typeof c.title === 'string') textParts.push(c.title);
      if (typeof c.description === 'string') textParts.push(c.description);
    });
  }
  const text = textParts.join(' ');
  if (!text) return Array.from(categories);

  Object.entries(TIER1_CONSTRAINT_HINTS).forEach(([category, patterns]) => {
    if (patterns.some((p) => p.test(text))) {
      categories.add(category);
    }
  });
  return Array.from(categories);
}

function inferCategoriesFromDayCards(dayCards: DayCard[] | undefined): string[] {
  if (!dayCards || dayCards.length === 0) return [];
  const allowed = new Set(ALL_CATEGORIES.map((c) => c.value));
  const inferred = new Set<string>();
  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      const category = resolveBlockCategory(block);
      if (category && allowed.has(category)) inferred.add(category);
      inferConstraintCategories(block).forEach((c) => {
        if (allowed.has(c)) inferred.add(c);
      });
    });
  });
  return Array.from(inferred);
}

function inferDayPreferencesFromDayCards(dayCards: DayCard[] | undefined): Record<string, number> {
  if (!dayCards || dayCards.length === 0) return {};
  const allowed = new Set(ALL_CATEGORIES.map((c) => c.value));
  const categoryToDays = new Map<string, Set<number>>();

  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      const category = resolveBlockCategory(block);
      if (category && allowed.has(category)) {
        const days = categoryToDays.get(category) ?? new Set<number>();
        days.add(card.day_number);
        categoryToDays.set(category, days);
      }
      inferConstraintCategories(block).forEach((constraintCategory) => {
        if (!allowed.has(constraintCategory)) return;
        const days = categoryToDays.get(constraintCategory) ?? new Set<number>();
        days.add(card.day_number);
        categoryToDays.set(constraintCategory, days);
      });
    });
  });

  const counts: Record<string, number> = {};
  categoryToDays.forEach((days, category) => {
    counts[category] = days.size;
  });
  return counts;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function ActivitiesSheetInner({
  open,
  onOpenChange,
  enabled,
  settings,
  hasExplicitSettings = false,
  hasDestination,
  onToggle,
  onSaveSettings,
  onOpenDestination,
}: ActivitiesSheetProps) {
  const { toast } = useToast();
  const dayCards = useDocumentStore(useShallow((s) => s.document?.day_cards));
  const inferredCategories = useMemo(() => inferCategoriesFromDayCards(dayCards), [dayCards]);
  const inferredDayPreferences = useMemo(() => inferDayPreferencesFromDayCards(dayCards), [dayCards]);
  const normalizedSettingCategories = useMemo(
    () =>
      Array.from(
        new Set(
          (settings.categories ?? [])
            .map((category) => canonicalCategoryKey(category))
            .filter((category): category is string => !!category)
        )
      ),
    [settings.categories]
  );
  const normalizedSettingDayPreferences = useMemo(() => {
    const normalizedEntries: Array<[string, number]> = [];
    Object.entries(settings.day_preferences ?? {}).forEach(([rawCategory, rawDays]) => {
      const category = canonicalCategoryKey(rawCategory);
      if (!category || typeof rawDays !== 'number' || !Number.isFinite(rawDays)) return;
      normalizedEntries.push([category, Math.max(0, Math.round(rawDays))]);
    });
    return Object.fromEntries(normalizedEntries);
  }, [settings.day_preferences]);
  const hasItinerary = (dayCards?.length ?? 0) > 0;
  // If saved categories exist, use them. Otherwise:
  // - If user explicitly saved (even with []), respect that choice.
  // - If user never saved, infer from day cards for initial display.
  const effectiveInitialCategories = useMemo(
    () =>
      normalizedSettingCategories.length > 0
        ? normalizedSettingCategories
        : (hasExplicitSettings ? normalizedSettingCategories : inferredCategories),
    [normalizedSettingCategories, hasExplicitSettings, inferredCategories]
  );
  const effectiveInitialDayPreferences = useMemo(
    () => (hasItinerary
      ? Object.fromEntries(
          effectiveInitialCategories
            .map((cat) => [
              cat,
              inferredDayPreferences[cat] ?? normalizedSettingDayPreferences[cat],
            ] as const)
            .filter((entry): entry is [string, number] => entry[1] != null && entry[1] > 0)
        )
      : normalizedSettingDayPreferences),
    [
      hasItinerary,
      effectiveInitialCategories,
      inferredDayPreferences,
      normalizedSettingDayPreferences,
    ]
  );
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localCategories, setLocalCategories] = useState<string[]>(
    effectiveInitialCategories
  );
  const [localDayPreferences, setLocalDayPreferences] = useState<Record<string, number>>(
    effectiveInitialDayPreferences
  );
  const [localPace, setLocalPace] = useState<number | null>(
    settings.activities_per_day ?? 1
  );
  // Track which categories had their day-preference stepper manually adjusted.
  // Only these entries are sent in day_preferences on save — inferred defaults
  // and seed values (toggleCategory seeds with 1) are display-only.
  const [userAdjustedCategories, setUserAdjustedCategories] = useState<Set<string>>(new Set());
  const wasOpenRef = useRef(false);

  // Check if prerequisites met
  const prerequisitesMet = hasDestination;

  // Reset when opened
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setLocalEnabled(enabled);
      setLocalCategories(effectiveInitialCategories);
      setLocalDayPreferences(effectiveInitialDayPreferences);
      setLocalPace(settings.activities_per_day ?? 1);
      setUserAdjustedCategories(new Set());
    }
    wasOpenRef.current = open;
  }, [open, enabled, effectiveInitialCategories, effectiveInitialDayPreferences, settings.activities_per_day]);

  // Handle toggle (commits immediately)
  const handleToggle = useCallback(
    (checked: boolean) => {
      if (checked && !prerequisitesMet) {
        return;
      }
      setLocalEnabled(checked);
      onToggle(checked);
      toast(checked ? 'Activities included' : 'Activities removed');
    },
    [prerequisitesMet, onToggle, toast]
  );

  // Handle save preferences
  const handleSave = useCallback(() => {
    // Only send day_preferences for categories the user explicitly adjusted via stepper.
    // Inferred defaults and seed values (from toggleCategory) are display-only.
    // Also strip keys for categories that were removed.
    const activeCategorySet = new Set(localCategories);
    const cleanedDayPreferences = Object.fromEntries(
      Object.entries(localDayPreferences).filter(
        ([cat]) => activeCategorySet.has(cat) && userAdjustedCategories.has(cat)
      )
    );
    onSaveSettings({
      categories: localCategories,
      skill_level: null,
      day_preferences: cleanedDayPreferences,
      activities_per_day: localPace,
    });
    toast('Activity preferences saved');
    onOpenChange(false);
  }, [localCategories, localDayPreferences, localPace, userAdjustedCategories, onSaveSettings, toast, onOpenChange]);

  // Toggle category — when adding, seed day_preferences with a default of 1
  const toggleCategory = useCallback((category: string) => {
    setLocalCategories((prev) => {
      if (prev.includes(category)) {
        return prev.filter((c) => c !== category);
      }
      // Seed day_preferences so the stepper doesn't show a contradictory "0"
      setLocalDayPreferences(dp =>
        category in dp ? dp : { ...dp, [category]: 1 }
      );
      return [...prev, category];
    });
  }, []);

  // Handle day preference changes
  const handleDayPreferenceChange = useCallback((category: string, days: number) => {
    setUserAdjustedCategories(prev => {
      if (prev.has(category)) return prev;
      return new Set([...prev, category]);
    });
    setLocalDayPreferences(prev => {
      if (days === 0) {
        const rest = { ...prev };
        delete rest[category];
        return rest; // Remove key when 0 (no preference)
      }
      return { ...prev, [category]: days };
    });
  }, []);

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Activities"
      hint="Configure activity preferences"
      footer={
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
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
            onClick={handleSave}
            disabled={!localEnabled}
            className={cn(
              localEnabled ? DS.actions.primary : DS.actions.primaryDisabled,
              'flex-1 px-4 py-2.5 font-semibold'
            )}
          >
            Save
          </button>
        </div>
      }
    >
      <ActivitiesSheetContent
        localEnabled={localEnabled}
        localCategories={localCategories}
        localDayPreferences={localDayPreferences}
        localPace={localPace}
        prerequisitesMet={prerequisitesMet}
        hasDestination={hasDestination}
        onToggle={handleToggle}
        onSetLocalPace={setLocalPace}
        onToggleCategory={toggleCategory}
        onDayPreferenceChange={handleDayPreferenceChange}
        onOpenDestination={onOpenDestination}
        onOpenChange={onOpenChange}
      />
    </BaseSheet>
  );
}

export const ActivitiesSheet = memo(ActivitiesSheetInner);

export default ActivitiesSheet;
