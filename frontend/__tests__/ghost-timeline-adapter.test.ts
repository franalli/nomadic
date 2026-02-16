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
      type: 'activity',
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

  it('uses default center when POI coordinates are invalid', () => {
    const center = calculateMapCenter([
      {
        id: 'bad-poi',
        title: 'Bad POI',
        type: 'activity',
        coordinates: { lat: Number.NaN, lng: Number.POSITIVE_INFINITY },
      } as MapPOI,
    ]);

    expect(center).toEqual({ lat: 25.2048, lng: 55.2708, zoom: 10 });
  });
});
