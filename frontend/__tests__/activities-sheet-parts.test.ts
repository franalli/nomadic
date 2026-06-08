import { describe, expect, it } from 'vitest';

import {
  buildSavePayload,
  deriveEffectiveInitialCategories,
} from '@/components/plan/sheets/ActivitiesSheetParts';

/**
 * Bug 1 regression: when an itinerary exists, the Activities modal MIRRORS it —
 * it opens showing exactly the inferred (badge) categories, ignoring saved
 * settings. Only with no itinerary does it fall back to saved settings.
 */
describe('deriveEffectiveInitialCategories', () => {
  it('mirrors inferred categories when an itinerary exists (overrides saved settings)', () => {
    const result = deriveEffectiveInitialCategories(
      ['saved'], // normalizedSettingCategories
      true, // hasExplicitSettings
      ['tours', 'cultural'] // inferredCategories (from day cards)
    );
    expect(result).toEqual(['tours', 'cultural']);
  });

  it('falls back to saved settings when there is no itinerary', () => {
    const result = deriveEffectiveInitialCategories(
      ['saved'], // normalizedSettingCategories
      true, // hasExplicitSettings
      [] // inferredCategories — no itinerary
    );
    expect(result).toEqual(['saved']);
  });

  it('returns [] when there is no itinerary and the user never saved settings', () => {
    const result = deriveEffectiveInitialCategories([], false, []);
    expect(result).toEqual([]);
  });
});

/**
 * Follow-up 2 regression: categories present on the itinerary that the modal
 * can't render as chips (e.g. 'kayaking') must survive a no-op Save when the
 * user is filtering, but an empty selection stays empty ("mixed = include all").
 */
describe('buildSavePayload preserves unrepresentable categories', () => {
  it('unions preserved categories into a non-empty selection', () => {
    const payload = buildSavePayload(
      ['cultural', 'tours'], // localCategories (user filtering)
      {},
      2,
      new Set(),
      ['kayaking', 'zipline'] // preserved (itinerary-present, not a chip)
    );
    expect(new Set(payload.categories)).toEqual(
      new Set(['cultural', 'tours', 'kayaking', 'zipline'])
    );
  });

  it('does NOT manufacture a filter from an empty selection', () => {
    const payload = buildSavePayload([], {}, 2, new Set(), ['kayaking']);
    // Empty stays empty -> backend maps [] -> None -> include all (mixed).
    expect(payload.categories).toEqual([]);
  });

  it('dedupes when a preserved category is somehow also selected', () => {
    const payload = buildSavePayload(['kayaking'], {}, 2, new Set(), ['kayaking']);
    expect(payload.categories).toEqual(['kayaking']);
  });
});
