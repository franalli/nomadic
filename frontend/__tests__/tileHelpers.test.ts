import { describe, expect, it } from 'vitest';

import {
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
});
