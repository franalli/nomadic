import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BookingSummary } from '@/components/plan/BookingSummary';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

describe('BookingSummary', () => {
  it('renders a deduped flights section from booked itinerary blocks', () => {
    const tiles: Record<string, Tile> = {
      hotel_1: {
        id: 'hotel_1',
        type: 'hotel',
        title: 'Canal House',
        currency: 'USD',
        deeplink_url: 'https://example.com/hotel_1',
      },
    };
    const dayCards: DayCard[] = [
      {
        day_number: 1,
        label: 'Arrival',
        blocks: [
          {
            period: 'morning',
            activity_type: 'Arrival',
            summary: 'Arrive in Rome',
            buffer_type: 'arrival',
            booking_category: 'flight',
            booked_tile: {
              id: 'flight_1',
              type: 'flight',
              title: 'ITA Airways - Direct',
              currency: 'USD',
              deeplink_url: 'https://example.com/flight_1',
              price_estimate: 420,
              price_basis: 'per_person',
            },
          },
        ],
      },
      {
        day_number: 4,
        label: 'Departure',
        blocks: [
          {
            period: 'evening',
            activity_type: 'Departure',
            summary: 'Depart Rome',
            buffer_type: 'departure',
            booking_category: 'flight',
            booked_tile: {
              id: 'flight_1',
              type: 'flight',
              title: 'ITA Airways - Direct',
              currency: 'USD',
              deeplink_url: 'https://example.com/flight_1',
              price_estimate: 420,
              price_basis: 'per_person',
            },
          },
        ],
      },
    ];

    render(
      <BookingSummary
        tiles={tiles}
        dayCards={dayCards}
        state="S3_ITINERARY_READY"
      />
    );

    expect(screen.getByText('Flights')).toBeInTheDocument();
    expect(screen.getAllByText('ITA Airways - Direct')).toHaveLength(1);
    expect(screen.getByRole('link', { name: /ita airways - direct/i })).toHaveAttribute(
      'href',
      'https://example.com/flight_1'
    );
  });
});
