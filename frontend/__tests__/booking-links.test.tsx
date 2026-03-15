import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { filterTilesByCategory } from '@/components/plan/booking/BookingDrawer';
import { BookingSummary } from '@/components/plan/BookingSummary';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

const FLIGHT_TILE: Tile = {
  id: 'flight_primary',
  type: 'flight',
  title: 'ITA Airways - Direct',
  subtitle: 'Departs 09:40',
  currency: 'USD',
  deeplink_url: 'https://www.aviasales.com/search/AMS0704FCO14041',
  partner_product_id: 'aviasales_abc123',
  price_estimate: 329,
};

describe('BookingSummary', () => {
  it('renders booked flight deeplinks from itinerary blocks', () => {
    const dayCards: DayCard[] = [
      {
        blocks: [
          {
            activity_type: 'Arrival',
            booking_category: 'flight',
            booked_tile: FLIGHT_TILE,
            buffer_type: 'arrival',
            period: 'morning',
            summary: 'Arrive in Rome',
          },
        ],
        day_number: 1,
        label: 'Arrival',
      },
    ];

    render(
      <BookingSummary
        tiles={{}}
        dayCards={dayCards}
        state="S3_ITINERARY_READY"
      />
    );

    expect(screen.getByText('Flights')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /ita airways - direct/i })).toHaveAttribute(
      'href',
      FLIGHT_TILE.deeplink_url
    );
  });
});

describe('filterTilesByCategory', () => {
  it('dedupes logical flight duplicates by partner product id', () => {
    const tiles: Record<string, Tile> = {
      flight_duplicate: {
        ...FLIGHT_TILE,
        id: 'flight_duplicate',
      },
      flight_primary: FLIGHT_TILE,
      flight_unique: {
        ...FLIGHT_TILE,
        id: 'flight_unique',
        deeplink_url: 'https://www.aviasales.com/search/AMS0704MAD14041',
        partner_product_id: 'aviasales_def456',
        title: 'KLM - 1 stop',
      },
    };

    expect(filterTilesByCategory(tiles, 'flight').map((tile) => tile.id)).toEqual([
      'flight_duplicate',
      'flight_unique',
    ]);
  });
});
