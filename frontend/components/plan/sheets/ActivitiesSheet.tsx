'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivitiesSheet
 *
 * Module sheet for activity preferences.
 * Prerequisites: Destination (dates optional)
 * Includes toggle + category selection + pace.
 */


import { Ticket } from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Stepper } from '@/components/ui/stepper';
import { Switch } from '@/components/ui/switch';
import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { ActivitySettings } from '@/types/document';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { BaseSheet } from './BaseSheet';
import { GatingBlocker } from './GatingBlocker';

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

// Activity categories — flat list, no visual distinction between tiers.
// Tier 1 (specialist) vs Tier 2 (experience) is a backend implementation detail.
const ALL_CATEGORIES = [
  { value: 'diving', label: 'Diving', icon: '🤿' },
  { value: 'hiking', label: 'Hiking', icon: '🥾' },
  { value: 'skiing', label: 'Skiing', icon: '⛷️' },
  { value: 'cycling', label: 'Cycling', icon: '🚴' },
  { value: 'sailing', label: 'Sailing', icon: '⛵' },
  { value: 'surfing', label: 'Surfing', icon: '🏄' },
  { value: 'cooking', label: 'Cooking', icon: '🍳' },
  { value: 'yoga', label: 'Yoga', icon: '🧘' },
  { value: 'cultural', label: 'Cultural', icon: '🏛️' },
  { value: 'tours', label: 'Tours', icon: '🎟️' },
  { value: 'temples', label: 'Temples', icon: '⛩️' },
  { value: 'nightlife', label: 'Nightlife', icon: '🎉' },
  { value: 'beach', label: 'Beach', icon: '🏖️' },
  { value: 'shopping', label: 'Shopping', icon: '🛍️' },
  { value: 'photography', label: 'Photography', icon: '📸' },
];

// Skill level options
const SKILL_OPTIONS = [
  { value: 'beginner', label: 'Beginner', description: 'Easy activities, no experience needed' },
  { value: 'intermediate', label: 'Intermediate', description: 'Some experience helpful' },
  { value: 'advanced', label: 'Advanced', description: 'Challenging activities for experienced' },
];

const NON_ACTIVITY_TYPES = new Set([
  'arrival', 'departure', 'check-in', 'check-out', 'check_in', 'check_out',
  'free_day', 'rest_day', 'buffer', 'decompression_buffer',
]);

const CATEGORY_ALIAS: Record<string, string> = {
  culture: 'cultural',
  tours: 'tours',
  attraction: 'tours',
  tourist_attraction: 'tours',
  point_of_interest: 'tours',
  travel_agency: 'tours',
  cultural_attraction: 'cultural',
  museum: 'cultural',
  art_gallery: 'cultural',
  historical_landmark: 'cultural',
  cultural_landmark: 'cultural',
  monument: 'cultural',
  plaza: 'cultural',
  ruins: 'cultural',
  fountain: 'cultural',
  hindu_temple: 'temples',
  temple: 'temples',
  church: 'cultural',
  place_of_worship: 'cultural',
  synagogue: 'cultural',
  mosque: 'cultural',
  restaurant: 'food',
  cafe: 'food',
  bar: 'food',
  bakery: 'food',
  meal_takeaway: 'food',
  meal_delivery: 'food',
  park: 'nature',
  natural_feature: 'nature',
  national_park: 'nature',
  campground: 'nature',
  zoo: 'nature',
  botanical_garden: 'nature',
  shopping_mall: 'shopping',
  market: 'shopping',
  store: 'shopping',
  clothing_store: 'shopping',
  department_store: 'shopping',
  beauty_salon: 'spa',
  gym: 'spa',
};

const TIER1_CONSTRAINT_HINTS: Record<string, RegExp[]> = {
  diving: [/\bdiv(e|ing|er|es)\b/i, /\bscuba\b/i, /\bno[- ]fly\b/i, /\bdecompression\b/i],
  hiking: [/\bhik(e|ing)\b/i, /\btrek\b/i, /\btrail\b/i],
  skiing: [/\bski(ing)?\b/i, /\bsnowboard(ing)?\b/i, /\baltitude\b/i],
  cycling: [/\bcycl(e|ing)\b/i, /\bbik(e|ing)\b/i],
  surfing: [/\bsurf(ing)?\b/i, /\bwave\b/i],
  sailing: [/\bsail(ing)?\b/i, /\byacht(ing)?\b/i, /\bmarine\b/i],
};

function toCategoryKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function canonicalCategoryKey(value: unknown): string | null {
  const key = toCategoryKey(value);
  if (!key) return null;
  const mapped = CATEGORY_ALIAS[key] ?? key;
  if (/(culture|cultural|heritage)/.test(key)) return 'cultural';
  if (/(museum|landmark|historic|monument|plaza|fountain)/.test(key)) return 'cultural';
  if (/(temple|church|worship|mosque|synagogue)/.test(key)) return 'temples';
  if (/(restaurant|cafe|bar|bakery|food|meal)/.test(key)) return 'food';
  if (/(park|garden|nature|zoo|camp)/.test(key)) return 'nature';
  if (/(shop|store|market|mall)/.test(key)) return 'shopping';
  if (/(spa|wellness|gym|beauty)/.test(key)) return 'spa';
  if (/(tour|point_of_interest|visitor|travel_agency)/.test(key)) return 'tours';
  return mapped;
}

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
  const dayCards = useDocumentStore((s) => s.document?.day_cards);
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
  // Only fall back to inferred categories when the user has never explicitly
  // saved activity settings. Once saved (even with empty categories []),
  // respect the user's choice — don't re-infer from day cards.
  const effectiveInitialCategories =
    hasExplicitSettings ? normalizedSettingCategories : inferredCategories;
  const effectiveInitialDayPreferences = hasItinerary
    ? Object.fromEntries(
        effectiveInitialCategories.map((cat) => [cat, inferredDayPreferences[cat] ?? normalizedSettingDayPreferences[cat] ?? 0])
      )
    : normalizedSettingDayPreferences;
  const [localEnabled, setLocalEnabled] = useState(enabled);
  const [localCategories, setLocalCategories] = useState<string[]>(
    effectiveInitialCategories
  );
  const [localSkillLevel, setLocalSkillLevel] = useState<string | null>(settings.skill_level || null);
  const [localDayPreferences, setLocalDayPreferences] = useState<Record<string, number>>(
    effectiveInitialDayPreferences
  );
  const wasOpenRef = useRef(false);

  // Check if prerequisites met
  const prerequisitesMet = hasDestination;

  // Reset when opened
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setLocalEnabled(enabled);
      setLocalCategories(effectiveInitialCategories);
      setLocalSkillLevel(settings.skill_level || null);
      setLocalDayPreferences(effectiveInitialDayPreferences);
    }
    wasOpenRef.current = open;
  }, [open, enabled, effectiveInitialCategories, effectiveInitialDayPreferences, settings.skill_level]);

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
    // Strip day_preferences keys for categories that were removed.
    // Without this, removing "hiking" leaves day_preferences:{hiking:4} in the payload,
    // which the backend sees as a request to schedule hiking days.
    const activeCategorySet = new Set(localCategories);
    const cleanedDayPreferences = Object.fromEntries(
      Object.entries(localDayPreferences).filter(([cat]) => activeCategorySet.has(cat))
    );
    onSaveSettings({
      categories: localCategories,
      skill_level: localSkillLevel,
      day_preferences: cleanedDayPreferences,
    });
    toast('Activity preferences saved');
    onOpenChange(false);
  }, [localCategories, localSkillLevel, localDayPreferences, onSaveSettings, toast, onOpenChange]);

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
      <div className="space-y-6">
        {/* Gating blocker */}
        <GatingBlocker
          featureLabel="activities"
          gates={[
            { label: 'Destination', met: hasDestination, onOpen: onOpenDestination },
          ]}
          onClose={() => onOpenChange(false)}
        />

        {/* Include toggle */}
        <div className="flex items-center justify-between py-3 border-b border-zinc-200 dark:border-white/10">
          <div className="flex items-center gap-2">
            <Ticket className="h-5 w-5 text-zinc-900 dark:text-white" />
            <span className="text-sm font-medium text-zinc-900 dark:text-white">
              Include activities
            </span>
          </div>
          <Switch
            checked={localEnabled}
            onCheckedChange={handleToggle}
            disabled={!prerequisitesMet && !localEnabled}
          />
        </div>

        {/* Preferences (disabled when toggle off) */}
        <div
          className={cn(
            'space-y-6 transition-opacity',
            !localEnabled && 'opacity-50 pointer-events-none'
          )}
        >
          {/* Activity Categories — single flat grid */}
          <div>
            <div className="grid grid-cols-2 gap-2">
              {ALL_CATEGORIES.map((option) => {
                const isSelected = localCategories.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleCategory(option.value)}
                    className={cn(
                      'flex items-center gap-2 px-3 py-3 rounded-lg text-sm font-medium',
                      'transition-all duration-150 text-left',
                      isSelected
                        ? 'bg-zinc-900 text-white border-2 border-zinc-900 shadow-md dark:bg-white dark:text-black dark:border-white'
                      : cn(
                          'bg-white border-2 border-zinc-200 text-zinc-600',
                          'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                          'dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400',
                          'dark:hover:bg-white/10 dark:hover:text-white dark:hover:border-white/40'
                        )
                    )}
                  >
                    <span>{option.icon}</span>
                    <span>{option.label}</span>
                  </button>
                );
              })}
            </div>
            {localCategories.length === 0 && (
              <p className="text-xs text-zinc-500 dark:text-zinc-500 mt-2">
                No categories selected = mixed recommendations
              </p>
            )}
          </div>

          {/* Day preferences — only when categories selected */}
          {localCategories.length > 0 && (
            <div>
              <h3 className={cn(DS.text.label, 'mb-3')}>
                Days per activity
              </h3>
              <p className="text-xs text-zinc-500 dark:text-zinc-500 mb-2">
                Set 0 for no preference
              </p>
              <div className="space-y-1">
                {localCategories.map((catValue) => {
                  const catDef = ALL_CATEGORIES.find(c => c.value === catValue);
                  return (
                    <div key={catValue} className="flex items-center justify-between py-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{catDef?.icon || '🏷️'}</span>
                        <span className="text-sm font-medium text-zinc-900 dark:text-white">
                          {catDef?.label || catValue}
                        </span>
                      </div>
                      <Stepper
                        value={localDayPreferences[catValue] || 0}
                        min={0}
                        max={7}
                        size="sm"
                        onChange={(val) => handleDayPreferenceChange(catValue, val)}
                        label={`${catDef?.label || catValue} days`}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Skill Level */}
          <div>
            <h3 className={cn(DS.text.label, 'mb-3')}>
              Skill level
            </h3>
            <div className="space-y-2">
              {SKILL_OPTIONS.map((option) => {
                const isSelected = localSkillLevel === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setLocalSkillLevel(option.value)}
                    className={cn(
                      'w-full flex flex-col items-start px-4 py-3.5 rounded-lg',
                      'transition-all duration-150 text-left',
                      isSelected
                        // Selected: Strong ring for emphasis
                        ? 'bg-zinc-900 text-white border-2 border-transparent shadow-md dark:bg-white dark:text-black dark:border-transparent'
                        // Inactive: Glass Fill
                        : cn(
                            'bg-white border-2 border-zinc-200',
                            'hover:border-zinc-900 hover:bg-zinc-50',
                            // Dark: Glass substance
                            'dark:bg-white/5 dark:border-2 dark:border-white/15',
                            'dark:hover:bg-white/10 dark:hover:border-white/40'
                          )
                    )}
                  >
                    <span
                      className={cn(
                        'text-sm font-semibold',
                        isSelected
                          ? 'text-white dark:text-black'
                          : 'text-zinc-600 dark:text-zinc-400'
                      )}
                    >
                      {option.label}
                    </span>
                    <span className={cn(
                      'text-xs',
                      isSelected
                        ? 'text-zinc-300 dark:text-zinc-600'
                        : 'text-zinc-500 dark:text-zinc-500'
                    )}>
                      {option.description}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </BaseSheet>
  );
}

export const ActivitiesSheet = memo(ActivitiesSheetInner);

export default ActivitiesSheet;
