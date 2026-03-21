import { describe, expect, it } from 'vitest';

import {
  calculateMapCenter,
  extractPOIsFromDayCards,
  type MapPOI,
} from '@/lib/ghost-timeline-adapter';
import type { DayCard, StrategySection } from '@/types/plan-envelope';

function makeDayCards(): DayCard[] {
  return [
    {
      day_number: 1,
      label: 'Day 1',
      blocks: [
        {
          id: 'act-1',
          period: 'morning',
          activity_type: 'diving',
          summary: 'Tulamben Dive',
          coordinates: { lat: -8.274, lng: 115.593 },
        },
      ],
    },
  ];
}

function makeStrategySections(): StrategySection[] {
  return [
    {
      id: 'strategy-diving',
      title: 'Diving',
      specialist_type: 'diving',
      principles: [],
      must_dos: [],
      optional_upgrades: [],
      logistics_notes: [],
      bullets: [],
      content_added: [
        {
          title: 'Tulamben Dive',
          coordinates: [115.593, -8.274],
        },
      ],
    },
  ];
}

describe('extractPOIsFromDayCards memo behavior', () => {
  it('returns cached POIs for identical fingerprint and destination', () => {
    const dayCards = makeDayCards();
    const sections = makeStrategySections();

    const first = extractPOIsFromDayCards(dayCards, sections, 'Bali', 'memo-hit-1');
    const second = extractPOIsFromDayCards(dayCards, sections, 'Bali', 'memo-hit-1');

    expect(second).toBe(first);
    expect(second).toHaveLength(1);
    expect(second[0]).toMatchObject<MapPOI>({
      id: 'act-1',
      title: 'Tulamben Dive',
      type: 'diving',
      coordinates: { lat: -8.274, lng: 115.593 },
    });
  });

  it('recomputes when fingerprint changes', () => {
    const dayCards = makeDayCards();
    const sections = makeStrategySections();

    const first = extractPOIsFromDayCards(dayCards, sections, 'Bali', 'memo-miss-a');
    const second = extractPOIsFromDayCards(dayCards, sections, 'Bali', 'memo-miss-b');

    expect(second).not.toBe(first);
    expect(second).toEqual(first);
  });

  it('memoizes fallback output when day cards are missing', () => {
    const sections = makeStrategySections();

    const first = extractPOIsFromDayCards(undefined, sections, 'Bali', 'memo-fallback');
    const second = extractPOIsFromDayCards(undefined, sections, 'Bali', 'memo-fallback');

    expect(first).toHaveLength(1);
    expect(first[0].title).toBe('Tulamben Dive');
    expect(second).toBe(first);
  });

  it('propagates metadata in strategy-section fallback POIs', () => {
    const sections: StrategySection[] = [
      {
        id: 'strategy-yoga',
        title: 'Yoga',
        specialist_type: 'yoga',
        principles: [],
        must_dos: [],
        optional_upgrades: [],
        logistics_notes: [],
        bullets: [],
        content_added: [
          {
            title: 'Sunrise Flow',
            day: 2,
            coordinates: [100.5018, 13.7563],
            intensity: 'moderate',
            duration: '1.5h',
            rating: 4.8,
            review_count: 220,
            price_level: 1,
          } as unknown as NonNullable<StrategySection['content_added']>[number],
        ],
      },
    ];

    const pois = extractPOIsFromDayCards(undefined, sections, 'Bangkok', 'memo-fallback-meta');

    expect(pois).toHaveLength(1);
    expect(pois[0]).toMatchObject({
      type: 'yoga',
      source: 'specialist',
      dayNumber: 2,
      intensity: 'moderate',
      duration: '1.5h',
      rating: 4.8,
      reviewCount: 220,
      priceLevel: 1,
    });
  });

  it('skips invalid day-card coordinates and falls back to strategy-section POIs', () => {
    const invalidDayCards: DayCard[] = [
      {
        day_number: 1,
        label: 'Day 1',
        blocks: [
          {
            id: 'bad-1',
            period: 'morning',
            activity_type: 'diving',
            summary: 'Invalid Coordinates Block',
            coordinates: { lat: 999, lng: 999 },
          },
        ],
      },
    ];
    const sections = makeStrategySections();

    const pois = extractPOIsFromDayCards(
      invalidDayCards,
      sections,
      'Bali',
      'memo-invalid-coordinates-fallback'
    );

    expect(pois).toHaveLength(1);
    expect(pois[0]).toMatchObject({
      title: 'Tulamben Dive',
      coordinates: { lat: -8.274, lng: 115.593 },
    });
  });

  it('returns null when POI coordinates are invalid', () => {
    const center = calculateMapCenter([
      {
        id: 'bad-poi',
        title: 'Bad POI',
        type: 'activity',
        coordinates: { lat: Number.NaN, lng: Number.POSITIVE_INFINITY },
      } as MapPOI,
    ]);

    expect(center).toBeNull();
  });

  it('derives type from tile metadata and prefers explicit provenance', () => {
    const dayCards: DayCard[] = [
      {
        day_number: 3,
        label: 'Day 3',
        blocks: [
          {
            id: 'tier2-1',
            period: 'morning',
            activity_type: '',
            specialist_type: 'yoga',
            summary: 'Sunrise Yoga Session',
            coordinates: { lat: 13.7563, lng: 100.5018 },
            intensity: 'light',
            duration: '1.5h',
            rating: 4.7,
            review_count: 144,
            price_level: 2,
            activity_domain: 'tier2',
            activity_provenance: 'ai_suggested',
            booked_tile: {
              id: 'tile-yoga-1',
              type: 'activity',
              title: 'Sunrise Yoga Session',
              currency: 'USD',
              deeplink_url: 'https://example.com',
              meta: {
                category: 'yoga',
              },
            },
          },
          {
            id: 'manual-food-3',
            period: 'afternoon',
            activity_type: '',
            specialist_type: 'food',
            summary: 'Canal Food Crawl',
            coordinates: { lat: 13.759, lng: 100.505 },
            activity_domain: 'tier2',
            activity_provenance: 'user_browse_added',
            booked_tile: {
              id: 'tile-food-1',
              type: 'activity',
              title: 'Canal Food Crawl',
              currency: 'USD',
              deeplink_url: 'https://example.com',
              meta: {
                category: 'food',
              },
            },
          },
        ],
      },
    ];

    const pois = extractPOIsFromDayCards(dayCards, undefined, 'Bangkok', 'memo-tier2-browse');

    expect(pois).toHaveLength(2);
    expect(pois[0]).toMatchObject({
      type: 'yoga',
      source: 'itinerary',
      intensity: 'light',
      duration: '1.5h',
      rating: 4.7,
      reviewCount: 144,
      priceLevel: 2,
    });
    expect(pois[1]).toMatchObject({ type: 'food', source: 'browse' });
  });

  it('normalizes religious-site booked-tile categories to temples', () => {
    const dayCards: DayCard[] = [
      {
        day_number: 4,
        label: 'Day 4',
        blocks: [
          {
            id: 'temple-1',
            period: 'morning',
            activity_type: '',
            summary: 'Old Cathedral Visit',
            coordinates: { lat: 41.0082, lng: 28.9784 },
            booked_tile: {
              id: 'tile-church-1',
              type: 'activity',
              title: 'Old Cathedral Visit',
              currency: 'USD',
              deeplink_url: 'https://example.com/church',
              category: 'church',
              meta: {},
            },
          },
          {
            id: 'temple-2',
            period: 'afternoon',
            activity_type: '',
            summary: 'Grand Mosque Walk',
            coordinates: { lat: 41.0055, lng: 28.9769 },
            booked_tile: {
              id: 'tile-mosque-1',
              type: 'activity',
              title: 'Grand Mosque Walk',
              currency: 'USD',
              deeplink_url: 'https://example.com/mosque',
              meta: {
                category: 'grand_mosque',
              },
            },
          },
        ],
      },
    ];

    const pois = extractPOIsFromDayCards(dayCards, undefined, 'Istanbul', 'memo-religious-sites');

    expect(pois).toHaveLength(2);
    expect(pois[0]).toMatchObject({ type: 'temples' });
    expect(pois[1]).toMatchObject({ type: 'temples' });
  });
});
