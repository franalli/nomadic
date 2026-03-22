import type { LucideIcon } from 'lucide-react';
import { Leaf, Sun, Zap } from 'lucide-react';

import type { DayCard } from '@/types/plan-envelope';

import { inferConstraintCategories, resolveBlockCategory } from '../tripSummaryUtils';

// Activity categories -- flat list, no visual distinction between tiers.
// Tier 1 (specialist) vs Tier 2 (experience) is a backend implementation detail.
export const ALL_CATEGORIES = [
  { value: 'diving', label: 'Diving', icon: '\u{1F93F}' },
  { value: 'hiking', label: 'Hiking', icon: '\u{1F97E}' },
  { value: 'skiing', label: 'Skiing', icon: '\u26F7\uFE0F' },
  { value: 'cycling', label: 'Cycling', icon: '\u{1F6B4}' },
  { value: 'sailing', label: 'Sailing', icon: '\u26F5' },
  { value: 'surfing', label: 'Surfing', icon: '\u{1F3C4}' },
  { value: 'cooking', label: 'Cooking', icon: '\u{1F373}' },
  { value: 'yoga', label: 'Yoga', icon: '\u{1F9D8}' },
  { value: 'cultural', label: 'Cultural', icon: '\u{1F3DB}\uFE0F' },
  { value: 'tours', label: 'Tours', icon: '\u{1F39F}\uFE0F' },
  { value: 'temples', label: 'Temples', icon: '\u26E9\uFE0F' },
  { value: 'nightlife', label: 'Nightlife', icon: '\u{1F389}' },
  { value: 'beach', label: 'Beach', icon: '\u{1F3D6}\uFE0F' },
  { value: 'shopping', label: 'Shopping', icon: '\u{1F6CD}\uFE0F' },
  { value: 'photography', label: 'Photography', icon: '\u{1F4F8}' },
];

export const PACE_OPTIONS: readonly { value: number; label: string; icon: LucideIcon }[] = [
  { value: 1, label: 'Relaxed', icon: Leaf },
  { value: 2, label: 'Moderate', icon: Sun },
  { value: 3, label: 'Packed', icon: Zap },
] as const;

export function inferCategoriesFromDayCards(dayCards: DayCard[] | undefined): string[] {
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

export function inferDayPreferencesFromDayCards(dayCards: DayCard[] | undefined): Record<string, number> {
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
