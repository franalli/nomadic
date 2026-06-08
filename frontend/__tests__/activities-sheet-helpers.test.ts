import { describe, expect, it } from 'vitest';

import {
  ALL_CATEGORIES,
  inferCategoriesFromDayCards,
  inferDayPreferencesFromDayCards,
  inferUnrepresentableCategoriesFromDayCards,
} from '@/components/plan/sheets/activitiesSheetHelpers';
import type { DayCard } from '@/types/plan-envelope';

/**
 * Bug 1 regression: the Activities modal must MIRROR the itinerary. Inference uses
 * the SAME resolver the day-card badges use (resolveActivityCategory), so the
 * inferred set equals exactly the set of category badges visible on the cards.
 */

function block(mapType: string, extra: Record<string, unknown> = {}) {
  return { period: 'morning', activity_type: 'visit', summary: 'x', map_type: mapType, ...extra };
}

const DAY_CARDS = [
  {
    day_number: 1,
    label: 'Day 1',
    blocks: [block('tours'), block('cultural')],
  },
  {
    day_number: 2,
    label: 'Day 2',
    blocks: [block('cultural')],
  },
] as unknown as DayCard[];

describe('inferCategoriesFromDayCards', () => {
  it('mirrors the category badges on the day cards (exactly those, no extras)', () => {
    const inferred = inferCategoriesFromDayCards(DAY_CARDS);
    expect(new Set(inferred)).toEqual(new Set(['tours', 'cultural']));
  });

  it('represents food/nature badges that the old vocabulary dropped', () => {
    const cards = [
      {
        day_number: 1,
        label: 'Day 1',
        // 'restaurant' canonicalizes to 'food'; 'nature' resolves to 'nature'.
        blocks: [block('restaurant'), block('nature')],
      },
    ] as unknown as DayCard[];

    const inferred = inferCategoriesFromDayCards(cards);
    expect(inferred).toContain('food');
    expect(inferred).toContain('nature');
    // Both are now representable in the modal vocabulary.
    const values = new Set(ALL_CATEGORIES.map((c) => c.value));
    expect(values.has('food')).toBe(true);
    expect(values.has('nature')).toBe(true);
  });

  it('mirrors Tier-1 specialist badges (climbing, wildlife_safari) instead of dropping them', () => {
    // Regression: these are visible day-card badges; if ALL_CATEGORIES omits them
    // the inferred set drops them and a benign open+Save silently removes the
    // specialist from the itinerary.
    const cards = [
      {
        day_number: 1,
        label: 'Day 1',
        blocks: [block('climbing'), block('wildlife_safari')],
      },
    ] as unknown as DayCard[];

    const inferred = inferCategoriesFromDayCards(cards);
    expect(new Set(inferred)).toEqual(new Set(['climbing', 'wildlife_safari']));
    const values = new Set(ALL_CATEGORIES.map((c) => c.value));
    expect(values.has('climbing')).toBe(true);
    expect(values.has('wildlife_safari')).toBe(true);
  });

  it('ignores buffer/safety blocks (e.g. a diving decompression buffer) that show no badge', () => {
    // resolveActivityCategory has no buffer guard; a buffer carrying specialist_type
    // must NOT leak into the inferred set or inflate the day count.
    const cards = [
      {
        day_number: 1,
        label: 'Day 1',
        blocks: [block('diving')],
      },
      {
        day_number: 2,
        label: 'Day 2',
        blocks: [
          { period: 'morning', activity_type: 'decompression_buffer', is_buffer: true, specialist_type: 'diving', summary: 'No-fly buffer' },
        ],
      },
    ] as unknown as DayCard[];

    expect(new Set(inferCategoriesFromDayCards(cards))).toEqual(new Set(['diving']));
    // Day 2's buffer must NOT count as a diving day.
    expect(inferDayPreferencesFromDayCards(cards)).toEqual({ diving: 1 });
  });

  it('does NOT infer specialist-constraint categories that are not shown as badges', () => {
    // A block with only constraint text (no map_type / specialist_type) must not
    // contribute a category — the divergent inferConstraintCategories path is gone.
    const cards = [
      {
        day_number: 1,
        label: 'Day 1',
        blocks: [
          { period: 'morning', activity_type: 'buffer', summary: 'No-fly buffer', constraints: ['no-fly'] },
        ],
      },
    ] as unknown as DayCard[];

    expect(inferCategoriesFromDayCards(cards)).toEqual([]);
  });

  it('returns [] for missing / empty day cards', () => {
    expect(inferCategoriesFromDayCards(undefined)).toEqual([]);
    expect(inferCategoriesFromDayCards([])).toEqual([]);
  });
});

describe('inferUnrepresentableCategoriesFromDayCards', () => {
  it('returns badge categories the modal cannot show as chips (open-ended Tier-2 keys)', () => {
    const cards = [
      {
        day_number: 1,
        label: 'Day 1',
        // 'kayaking'/'zipline' are not in ALL_CATEGORIES; 'cultural' is.
        blocks: [block('kayaking'), block('zipline'), block('cultural')],
      },
    ] as unknown as DayCard[];

    const unrepresentable = inferUnrepresentableCategoriesFromDayCards(cards);
    expect(new Set(unrepresentable)).toEqual(new Set(['kayaking', 'zipline']));
    // Representable categories are excluded (they survive as normal chips).
    expect(unrepresentable).not.toContain('cultural');
  });

  it('ignores buffer blocks and returns [] for empty input', () => {
    const cards = [
      {
        day_number: 1,
        label: 'Day 1',
        blocks: [{ period: 'morning', activity_type: 'decompression_buffer', is_buffer: true, map_type: 'kayaking' }],
      },
    ] as unknown as DayCard[];
    expect(inferUnrepresentableCategoriesFromDayCards(cards)).toEqual([]);
    expect(inferUnrepresentableCategoriesFromDayCards(undefined)).toEqual([]);
  });
});

describe('inferDayPreferencesFromDayCards', () => {
  it('counts distinct day_numbers per resolved badge category', () => {
    const prefs = inferDayPreferencesFromDayCards(DAY_CARDS);
    // cultural appears on day 1 and day 2 -> 2; tours only on day 1 -> 1.
    expect(prefs).toEqual({ tours: 1, cultural: 2 });
  });

  it('returns {} for missing / empty day cards', () => {
    expect(inferDayPreferencesFromDayCards(undefined)).toEqual({});
    expect(inferDayPreferencesFromDayCards([])).toEqual({});
  });
});
