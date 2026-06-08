import type { LucideIcon } from 'lucide-react';
import { Leaf, Sun, Zap } from 'lucide-react';

import {
  isBadgedActivityBlock,
  resolveActivityCategory,
} from '@/components/plan/timeline/blocks/ActivityCardMeta.helpers';
import type { DayCard } from '@/types/plan-envelope';

// Activity categories -- flat list, no visual distinction between tiers.
// Tier 1 (specialist) vs Tier 2 (experience) is a backend implementation detail.
export const ALL_CATEGORIES = [
  { value: 'diving', label: 'Diving', icon: '\u{1F93F}' },
  { value: 'hiking', label: 'Hiking', icon: '\u{1F97E}' },
  { value: 'skiing', label: 'Skiing', icon: '\u26F7\uFE0F' },
  { value: 'cycling', label: 'Cycling', icon: '\u{1F6B4}' },
  { value: 'sailing', label: 'Sailing', icon: '\u26F5' },
  { value: 'surfing', label: 'Surfing', icon: '\u{1F3C4}' },
  { value: 'climbing', label: 'Climbing', icon: '\u{1F9D7}' },
  { value: 'wildlife_safari', label: 'Wildlife Safari', icon: '\u{1F981}' },
  { value: 'cooking', label: 'Cooking', icon: '\u{1F373}' },
  { value: 'yoga', label: 'Yoga', icon: '\u{1F9D8}' },
  { value: 'cultural', label: 'Cultural', icon: '\u{1F3DB}\uFE0F' },
  { value: 'tours', label: 'Tours', icon: '\u{1F39F}\uFE0F' },
  { value: 'temples', label: 'Temples', icon: '\u26E9\uFE0F' },
  { value: 'nightlife', label: 'Nightlife', icon: '\u{1F389}' },
  { value: 'beach', label: 'Beach', icon: '\u{1F3D6}\uFE0F' },
  { value: 'shopping', label: 'Shopping', icon: '\u{1F6CD}\uFE0F' },
  { value: 'photography', label: 'Photography', icon: '\u{1F4F8}' },
  { value: 'food', label: 'Food', icon: '\u{1F374}' },
  { value: 'nature', label: 'Nature', icon: '\u{1F333}' },
  { value: 'spa', label: 'Spa', icon: '\u{1F486}' },
  { value: 'adventure', label: 'Adventure', icon: '\u{1F3A2}' },
];

export const PACE_OPTIONS: readonly { value: number; label: string; icon: LucideIcon }[] = [
  { value: 1, label: 'Relaxed', icon: Leaf },
  { value: 2, label: 'Moderate', icon: Sun },
  { value: 3, label: 'Packed', icon: Zap },
] as const;

// Mirror the itinerary: use the SAME resolver the day-card category badges use
// (resolveActivityCategory). The inferred set therefore equals exactly the set of
// category badges visible on the day cards. Filtered against ALL_CATEGORIES so the
// modal can only show categories it can represent as chips.
export function inferCategoriesFromDayCards(dayCards: DayCard[] | undefined): string[] {
  if (!dayCards || dayCards.length === 0) return [];
  const allowed = new Set(ALL_CATEGORIES.map((c) => c.value));
  const inferred = new Set<string>();
  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      if (!isBadgedActivityBlock(block)) return;
      const key = resolveActivityCategory(block)?.key;
      if (key && allowed.has(key)) inferred.add(key);
    });
  });
  return Array.from(inferred);
}

// Categories present on the itinerary that the modal CANNOT represent as a chip
// (not in ALL_CATEGORIES) -- e.g. open-ended Tier-2 experience keys the backend
// emits like 'boating', 'kayaking', 'zipline', 'snorkeling'. These must be
// preserved through a no-op Save: otherwise mirroring seeds a category filter
// that omits them and the next rebuild drops them. Used by buildSavePayload.
export function inferUnrepresentableCategoriesFromDayCards(
  dayCards: DayCard[] | undefined
): string[] {
  if (!dayCards || dayCards.length === 0) return [];
  const allowed = new Set(ALL_CATEGORIES.map((c) => c.value));
  const unrepresentable = new Set<string>();
  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      if (!isBadgedActivityBlock(block)) return;
      const key = resolveActivityCategory(block)?.key;
      if (key && !allowed.has(key)) unrepresentable.add(key);
    });
  });
  return Array.from(unrepresentable);
}

export function inferDayPreferencesFromDayCards(dayCards: DayCard[] | undefined): Record<string, number> {
  if (!dayCards || dayCards.length === 0) return {};
  const allowed = new Set(ALL_CATEGORIES.map((c) => c.value));
  const categoryToDays = new Map<string, Set<number>>();

  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      if (!isBadgedActivityBlock(block)) return;
      const key = resolveActivityCategory(block)?.key;
      if (!key || !allowed.has(key)) return;
      const days = categoryToDays.get(key) ?? new Set<number>();
      days.add(card.day_number);
      categoryToDays.set(key, days);
    });
  });

  const counts: Record<string, number> = {};
  categoryToDays.forEach((days, category) => {
    counts[category] = days.size;
  });
  return counts;
}
