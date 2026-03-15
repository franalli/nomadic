import { describe, expect, it } from 'vitest';

import {
  getEffectiveTileDeeplinkUrl,
  getTileDeeplinkActionLabel,
  getTileDeeplinkPillLabel,
  isPartnerDeeplinkUrl,
} from '@/components/tiles/tileHelpers';
import type { Tile } from '@/types/tile';

function buildTile(overrides: Partial<Tile> = {}): Tile {
  return {
    id: 'tile_1',
    type: 'flight',
    title: 'Test tile',
    currency: 'USD',
    deeplink_url: 'https://example.com',
    ...overrides,
  };
}

describe('tileHelpers deeplink labels', () => {
  it('uses explicit Aviasales booking copy for flight deeplinks', () => {
    const tile = buildTile({
      deeplink_url: 'https://www.aviasales.com/search/AMS0704FCO14041',
    });

    expect(getTileDeeplinkPillLabel(tile)).toBe('Book on Aviasales');
    expect(getTileDeeplinkActionLabel(tile)).toBe('Book on Aviasales');
    expect(isPartnerDeeplinkUrl(tile.deeplink_url)).toBe(true);
  });

  it('uses explicit Google Flights booking copy for fallback deeplinks', () => {
    const tile = buildTile({
      deeplink_url: 'https://www.google.com/travel/flights?q=flights+from+AMS+to+FCO',
    });

    expect(getTileDeeplinkPillLabel(tile)).toBe('Book on Google Flights');
    expect(getTileDeeplinkActionLabel(tile)).toBe('Book on Google Flights');
    expect(isPartnerDeeplinkUrl(tile.deeplink_url)).toBe(true);
  });

  it('keeps non-flight mapping copy unchanged', () => {
    const tile = buildTile({
      type: 'hotel',
      deeplink_url: 'https://www.google.com/travel/hotels/Bali',
    });

    expect(getTileDeeplinkPillLabel(tile)).toBe('Map');
    expect(getTileDeeplinkActionLabel(tile)).toBe('View on Google Travel');
    expect(isPartnerDeeplinkUrl(tile.deeplink_url)).toBe(false);
  });

  it('treats direct Booking.com hotel links as booking deeplinks', () => {
    const tile = buildTile({
      type: 'hotel',
      deeplink_url: 'https://www.booking.com/searchresults.html?ss=Bali',
    });

    expect(getTileDeeplinkPillLabel(tile)).toBe('Book on Booking.com');
    expect(getTileDeeplinkActionLabel(tile)).toBe('Book on Booking.com');
    expect(isPartnerDeeplinkUrl(tile.deeplink_url)).toBe(true);
  });
});

describe('getEffectiveTileDeeplinkUrl', () => {
  it('recomputes direct Booking.com hotel search URLs from current trip inputs', () => {
    const tile = buildTile({
      type: 'hotel',
      title: 'Canal House',
      location_label: 'Amsterdam',
      meta: {
        destination: 'Amsterdam',
      },
      deeplink_url: 'https://www.booking.com/searchresults.html?ss=Canal+House&checkin=2026-05-01&checkout=2026-05-03&group_adults=1&group_children=0&no_rooms=2',
    });

    const effectiveUrl = new URL(
      getEffectiveTileDeeplinkUrl(tile, {
        start_date: '2026-06-10',
        end_date: '2026-06-15',
        adults: 3,
        children: 1,
      })
    );

    expect(effectiveUrl.hostname).toBe('www.booking.com');
    expect(effectiveUrl.pathname).toBe('/searchresults.html');
    expect(effectiveUrl.searchParams.get('ss')).toBe('Canal House, Amsterdam');
    expect(effectiveUrl.searchParams.get('checkin')).toBe('2026-06-10');
    expect(effectiveUrl.searchParams.get('checkout')).toBe('2026-06-15');
    expect(effectiveUrl.searchParams.get('group_adults')).toBe('3');
    expect(effectiveUrl.searchParams.get('group_children')).toBe('1');
    expect(effectiveUrl.searchParams.get('no_rooms')).toBe('2');
  });

  it('preserves booking affiliate aid while refreshing hotel search params', () => {
    const tile = buildTile({
      type: 'hotel',
      title: 'Canal House',
      meta: {
        destination: 'Amsterdam',
      },
      deeplink_url: 'https://www.booking.com/searchresults.html?aid=987654&ss=Canal+House&checkin=2026-05-01&checkout=2026-05-03&group_adults=1',
    });

    const effectiveUrl = new URL(
      getEffectiveTileDeeplinkUrl(tile, {
        start_date: '2026-07-20',
        end_date: '2026-07-24',
        adults: 2,
        children: 0,
      })
    );

    expect(effectiveUrl.searchParams.get('aid')).toBe('987654');
    expect(effectiveUrl.searchParams.get('checkin')).toBe('2026-07-20');
    expect(effectiveUrl.searchParams.get('checkout')).toBe('2026-07-24');
    expect(effectiveUrl.searchParams.get('group_adults')).toBe('2');
    expect(effectiveUrl.searchParams.get('group_children')).toBe('0');
  });

  it('reuses traveler counts from the original Booking.com deeplink when trip inputs omit them', () => {
    const tile = buildTile({
      type: 'hotel',
      title: 'Canal House',
      meta: {
        destination: 'Amsterdam',
      },
      deeplink_url:
        'https://www.booking.com/searchresults.html?ss=Canal+House&checkin=2026-05-01&checkout=2026-05-03&group_adults=1&group_children=2&no_rooms=2',
    });

    const effectiveUrl = new URL(
      getEffectiveTileDeeplinkUrl(tile, {
        start_date: '2026-07-20',
        end_date: '2026-07-24',
        adults: null,
        children: null,
      })
    );

    expect(effectiveUrl.searchParams.get('checkin')).toBe('2026-07-20');
    expect(effectiveUrl.searchParams.get('checkout')).toBe('2026-07-24');
    expect(effectiveUrl.searchParams.get('group_adults')).toBe('1');
    expect(effectiveUrl.searchParams.get('group_children')).toBe('2');
    expect(effectiveUrl.searchParams.get('no_rooms')).toBe('2');
  });

  it('recomputes Google Travel hotel links from current trip inputs', () => {
    const tile = buildTile({
      type: 'hotel',
      title: 'Canal House',
      meta: {
        destination: 'Amsterdam',
      },
      deeplink_url:
        'https://www.google.com/travel/hotels/entity/abc123?gl=nl&hl=en&q=Canal+House',
    });

    const effectiveUrl = new URL(
      getEffectiveTileDeeplinkUrl(tile, {
        start_date: '2026-08-01',
        end_date: '2026-08-05',
        adults: 2,
        children: 1,
      })
    );

    expect(effectiveUrl.origin).toBe('https://www.google.com');
    expect(effectiveUrl.pathname).toBe('/travel/hotels');
    expect(effectiveUrl.searchParams.get('q')).toBe('Canal House, Amsterdam');
    expect(effectiveUrl.searchParams.get('brd_dates')).toBe('2026-08-01,2026-08-05');
    expect(effectiveUrl.searchParams.get('brd_occupancy')).toBe('3');
    expect(effectiveUrl.searchParams.get('gl')).toBe('nl');
    expect(effectiveUrl.searchParams.get('hl')).toBe('en');
  });

  it('upgrades Google Maps hotel links to dated Google Travel searches', () => {
    const tile = buildTile({
      type: 'hotel',
      title: 'Canal House',
      meta: {
        destination: 'Amsterdam',
      },
      deeplink_url: 'https://maps.google.com/?q=place_id:ChIJ123',
    });

    const effectiveUrl = new URL(
      getEffectiveTileDeeplinkUrl(tile, {
        start_date: '2026-09-10',
        end_date: '2026-09-12',
        adults: 2,
        children: 0,
      })
    );

    expect(effectiveUrl.origin).toBe('https://www.google.com');
    expect(effectiveUrl.pathname).toBe('/travel/hotels');
    expect(effectiveUrl.searchParams.get('q')).toBe('Canal House, Amsterdam');
    expect(effectiveUrl.searchParams.get('brd_dates')).toBe('2026-09-10,2026-09-12');
    expect(effectiveUrl.searchParams.get('brd_occupancy')).toBe('2');
  });

  it('leaves unrelated non-Booking deeplinks unchanged', () => {
    const tile = buildTile({
      type: 'hotel',
      deeplink_url: 'https://example.com/hotels/canal-house',
    });

    expect(
      getEffectiveTileDeeplinkUrl(tile, {
        start_date: '2026-08-01',
        end_date: '2026-08-05',
        adults: 2,
        children: 0,
      })
    ).toBe(tile.deeplink_url);
  });
});
