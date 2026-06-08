import { describe, expect, it } from 'vitest';

import { inferCategoriesFromDayCards as chipInferCategories } from '@/components/plan/ChipGroup';
import { deriveScheduledDayCounts, resolveBlockCategory } from '@/components/plan/tripSummaryUtils';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

/**
 * Follow-up 1: the pill row (deriveScheduledDayCounts) and the chip row
 * (ChipGroup.inferCategoriesFromDayCards) must mirror the day-card badges via the
 * single resolver (resolveBlockCategory -> resolveActivityCategory), with NO
 * constraint-derived categories that aren't badged.
 */

function block(extra: Record<string, unknown> = {}) {
  return { period: 'morning', activity_type: 'visit', summary: 'x', ...extra };
}

describe('resolveBlockCategory (single resolver, delegates to badge resolver)', () => {
  it('mirrors the day-card badge', () => {
    expect(resolveBlockCategory(block({ map_type: 'tours' }) as unknown as DayBlock)).toBe('tours');
    // 'restaurant' canonicalizes to 'food' the same way the badge does.
    expect(resolveBlockCategory(block({ map_type: 'restaurant' }) as unknown as DayBlock)).toBe('food');
  });

  it('returns null for buffer / non-activity blocks (they show no badge)', () => {
    expect(
      resolveBlockCategory(
        block({ is_buffer: true, specialist_type: 'diving' }) as unknown as DayBlock
      )
    ).toBeNull();
    expect(
      resolveBlockCategory(block({ activity_type: 'arrival' }) as unknown as DayBlock)
    ).toBeNull();
  });
});

describe('deriveScheduledDayCounts mirrors badges (no constraint injection)', () => {
  const cards = [
    { day_number: 1, label: 'D1', blocks: [block({ map_type: 'diving' })] },
    {
      day_number: 2,
      label: 'D2',
      // A diving no-fly buffer carries specialist_type='diving' but shows no badge.
      blocks: [
        block({ activity_type: 'decompression_buffer', is_buffer: true, specialist_type: 'diving', summary: 'No-fly buffer' }),
      ],
    },
  ] as unknown as DayCard[];

  it('counts only badge days, not constraint-only buffer days', () => {
    const counts = deriveScheduledDayCounts(cards, []);
    // diving badge appears only on day 1; the day-2 buffer must NOT add a day.
    expect(counts.get('diving')).toBe(1);
  });
});

describe('ChipGroup.inferCategoriesFromDayCards mirrors badges', () => {
  it('does not inject constraint categories from buffer blocks', () => {
    const cards = [
      {
        day_number: 1,
        label: 'D1',
        blocks: [block({ map_type: 'tours' }), block({ is_buffer: true, specialist_type: 'diving' })],
      },
    ] as unknown as DayCard[];
    expect(new Set(chipInferCategories(cards))).toEqual(new Set(['tours']));
  });
});
