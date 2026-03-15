import { describe, expect, it } from 'vitest';

import {
  buildDayCardsFingerprint,
  selectPoiDayCardSnapshot,
  shouldDelayPoiSnapshotPromotion,
} from '@/components/plan/strategyStagePoi';
import type { DayCard } from '@/types/plan-envelope';

type DayCardBlock = NonNullable<DayCard['blocks']>[number];

function makeDayCard(
  dayNumber: number,
  blockId: string,
  options?: {
    booked_tile?: DayCardBlock['booked_tile'];
    coordinates?: { lat: number; lng: number };
    activity_provenance?: DayCardBlock['activity_provenance'];
    duration?: DayCardBlock['duration'];
    intensity?: DayCardBlock['intensity'];
    price_level?: DayCardBlock['price_level'];
    rating?: DayCardBlock['rating'];
    review_count?: DayCardBlock['review_count'];
  },
): DayCard {
  return {
    day_number: dayNumber,
    label: `Day ${dayNumber}`,
    blocks: [
      {
        id: blockId,
        period: 'morning',
        activity_type: 'guided activity',
        summary: `Block ${blockId}`,
        booked_tile: options?.booked_tile,
        coordinates: options?.coordinates,
        activity_provenance: options?.activity_provenance,
        duration: options?.duration,
        intensity: options?.intensity,
        price_level: options?.price_level,
        rating: options?.rating,
        review_count: options?.review_count,
      },
    ],
  };
}

describe('buildDayCardsFingerprint', () => {
  it('returns a stable fingerprint for placed day cards', () => {
    const cards = [makeDayCard(1, 'dive-1'), makeDayCard(2, 'dive-2')];

    expect(buildDayCardsFingerprint(cards)).toBe('2:1:1:dive-1|2:1:dive-2');
  });

  it('returns null when there are no day cards', () => {
    expect(buildDayCardsFingerprint([])).toBeNull();
    expect(buildDayCardsFingerprint(undefined)).toBeNull();
  });

  it('ignores non-coordinate block churn when coordinate-bearing POIs stay the same', () => {
    const withCoords: DayCard[] = [
      makeDayCard(1, 'dive-1', { coordinates: { lat: -8.67, lng: 115.21 } }),
      makeDayCard(2, 'dive-2', { coordinates: { lat: -8.71, lng: 115.25 } }),
    ];
    const withExtraNoCoordBlock: DayCard[] = [
      makeDayCard(1, 'dive-1', { coordinates: { lat: -8.67, lng: 115.21 } }),
      {
        ...makeDayCard(2, 'dive-2', { coordinates: { lat: -8.71, lng: 115.25 } }),
        blocks: [
          ...makeDayCard(2, 'dive-2', { coordinates: { lat: -8.71, lng: 115.25 } }).blocks,
          {
            id: 'note-only',
            period: 'afternoon',
            activity_type: 'guided activity',
            summary: 'No map pin yet',
          },
        ],
      },
    ];

    expect(buildDayCardsFingerprint(withExtraNoCoordBlock)).toBe(
      buildDayCardsFingerprint(withCoords)
    );
  });

  it('changes when map-visible POI metadata changes without moving the pin', () => {
    const base = [
      makeDayCard(1, 'dive-1', {
        coordinates: { lat: -8.67, lng: 115.21 },
        activity_provenance: 'itinerary',
        duration: '2 hours',
        intensity: 'moderate',
        price_level: 2,
        rating: 4.8,
        review_count: 120,
      }),
    ];
    const metadataChanged = [
      makeDayCard(1, 'dive-1', {
        coordinates: { lat: -8.67, lng: 115.21 },
        activity_provenance: 'user_browse_added',
        duration: '3 hours',
        intensity: 'challenging',
        price_level: 3,
        rating: 4.9,
        review_count: 128,
      }),
    ];

    expect(buildDayCardsFingerprint(metadataChanged)).not.toBe(
      buildDayCardsFingerprint(base)
    );
  });

  it('changes when booked-tile type inputs change with stable coordinates', () => {
    const base = [
      makeDayCard(1, 'dive-1', {
        coordinates: { lat: -8.67, lng: 115.21 },
        booked_tile: {
          category: 'spa',
          tags: ['spa'],
        } as DayCardBlock['booked_tile'],
      }),
    ];
    const typeChanged = [
      makeDayCard(1, 'dive-1', {
        coordinates: { lat: -8.67, lng: 115.21 },
        booked_tile: {
          category: 'spa',
          tags: ['park'],
          map_type: 'nature',
          meta: {
            map_type: 'nature',
            category: 'nature',
          },
        } as DayCardBlock['booked_tile'],
      }),
    ];

    expect(buildDayCardsFingerprint(typeChanged)).not.toBe(
      buildDayCardsFingerprint(base)
    );
  });
});

describe('selectPoiDayCardSnapshot', () => {
  it('keeps the previous stable snapshot while streaming', () => {
    const stableCards = [makeDayCard(1, 'stable-1')];
    const currentCards = [makeDayCard(1, 'partial-1'), makeDayCard(2, 'partial-2')];

    const snapshot = selectPoiDayCardSnapshot({
      currentDayCards: currentCards,
      currentFingerprint: buildDayCardsFingerprint(currentCards),
      fallbackDayCards: currentCards,
      stableDayCards: stableCards,
      stableFingerprint: buildDayCardsFingerprint(stableCards),
      isStreaming: true,
    });

    expect(snapshot.dayCards).toEqual(stableCards);
    expect(snapshot.fingerprint).toBe(buildDayCardsFingerprint(stableCards));
    expect(snapshot.nextStableDayCards).toEqual(stableCards);
  });

  it('seeds a stable fingerprint from fallback cards when the store is not hydrated yet', () => {
    const fallbackCards = [makeDayCard(1, 'fallback-1'), makeDayCard(2, 'fallback-2')];
    const fallbackFingerprint = buildDayCardsFingerprint(fallbackCards);

    const snapshot = selectPoiDayCardSnapshot({
      currentDayCards: undefined,
      currentFingerprint: null,
      fallbackDayCards: fallbackCards,
      stableDayCards: undefined,
      stableFingerprint: null,
      isStreaming: true,
    });

    expect(snapshot.dayCards).toEqual(fallbackCards);
    expect(snapshot.fingerprint).toBe(fallbackFingerprint);
    expect(snapshot.nextStableDayCards).toEqual(fallbackCards);
    expect(snapshot.nextStableFingerprint).toBe(fallbackFingerprint);
  });

  it('keeps an empty stable snapshot self-consistent while streaming', () => {
    const fallbackCards = [makeDayCard(1, 'fallback-1')];

    const snapshot = selectPoiDayCardSnapshot({
      currentDayCards: undefined,
      currentFingerprint: null,
      fallbackDayCards: fallbackCards,
      stableDayCards: [],
      stableFingerprint: null,
      isStreaming: true,
    });

    expect(snapshot.dayCards).toEqual([]);
    expect(snapshot.fingerprint).toBeNull();
    expect(snapshot.nextStableDayCards).toEqual([]);
    expect(snapshot.nextStableFingerprint).toBeNull();
  });

  it('promotes the latest day cards once streaming finishes', () => {
    const currentCards = [makeDayCard(1, 'final-1'), makeDayCard(2, 'final-2')];
    const currentFingerprint = buildDayCardsFingerprint(currentCards);

    const snapshot = selectPoiDayCardSnapshot({
      currentDayCards: currentCards,
      currentFingerprint,
      fallbackDayCards: undefined,
      stableDayCards: [makeDayCard(1, 'stale-1')],
      stableFingerprint: 'stale',
      isStreaming: false,
    });

    expect(snapshot.dayCards).toEqual(currentCards);
    expect(snapshot.fingerprint).toBe(currentFingerprint);
    expect(snapshot.nextStableDayCards).toEqual(currentCards);
    expect(snapshot.nextStableFingerprint).toBe(currentFingerprint);
  });

  it('uses fallback cards after streaming when the store is still not hydrated', () => {
    const fallbackCards = [makeDayCard(1, 'fallback-1'), makeDayCard(2, 'fallback-2')];
    const fallbackFingerprint = buildDayCardsFingerprint(fallbackCards);

    const snapshot = selectPoiDayCardSnapshot({
      currentDayCards: undefined,
      currentFingerprint: null,
      fallbackDayCards: fallbackCards,
      stableDayCards: undefined,
      stableFingerprint: null,
      isStreaming: false,
    });

    expect(snapshot.dayCards).toEqual(fallbackCards);
    expect(snapshot.fingerprint).toBe(fallbackFingerprint);
    expect(snapshot.nextStableDayCards).toEqual(fallbackCards);
    expect(snapshot.nextStableFingerprint).toBe(fallbackFingerprint);
  });
});

describe('shouldDelayPoiSnapshotPromotion', () => {
  it('delays post-stream promotion when a settled snapshot already exists', () => {
    expect(
      shouldDelayPoiSnapshotPromotion({
        settledDayCards: [makeDayCard(1, 'stable-1')],
        settledFingerprint: 'stable-fingerprint',
        nextFingerprint: 'partial-fingerprint',
        isStreaming: false,
      })
    ).toBe(true);
  });

  it('does not delay while streaming', () => {
    expect(
      shouldDelayPoiSnapshotPromotion({
        settledDayCards: [makeDayCard(1, 'stable-1')],
        settledFingerprint: 'stable-fingerprint',
        nextFingerprint: 'partial-fingerprint',
        isStreaming: true,
      })
    ).toBe(false);
  });

  it('does not delay initial promotion when no settled snapshot exists yet', () => {
    expect(
      shouldDelayPoiSnapshotPromotion({
        settledDayCards: undefined,
        settledFingerprint: null,
        nextFingerprint: 'first-fingerprint',
        isStreaming: false,
      })
    ).toBe(false);
  });

  it('does not delay when the fingerprint is unchanged', () => {
    expect(
      shouldDelayPoiSnapshotPromotion({
        settledDayCards: [makeDayCard(1, 'stable-1')],
        settledFingerprint: 'same-fingerprint',
        nextFingerprint: 'same-fingerprint',
        isStreaming: false,
      })
    ).toBe(false);
  });

  it('delays transient clears when a settled fingerprint already exists', () => {
    expect(
      shouldDelayPoiSnapshotPromotion({
        settledDayCards: [makeDayCard(1, 'stable-1')],
        settledFingerprint: 'stable-fingerprint',
        nextFingerprint: null,
        isStreaming: false,
      })
    ).toBe(true);
  });
});
