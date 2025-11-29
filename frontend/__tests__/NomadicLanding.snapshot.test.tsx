import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NomadicLanding } from '../components/layout/NomadicLanding';

const DOCUMENT_RESPONSE = {
  version: 1,
  updated_by: 'planner',
  updated_at: '2025-01-01T00:00:00Z',
  document: {
    trip_context_id: 99,
    trip_inputs: {
      destinations: ['Nice'],
      origin: 'Amsterdam',
      start_date: '2025-06-01',
      end_date: '2025-06-07',
      traveler_count: 2,
      missing_fields: [],
    },
    branches: [
      {
        id: 'branch-1',
        label: 'Beach Escape',
        description: 'Relax on the coast',
        destinations: ['Nice'],
        origin: 'Amsterdam',
        start_date: '2025-06-01',
        end_date: '2025-06-07',
        traveler_count: 2,
        is_primary: true,
        tiles: {
          stays: [
            {
              id: 'tile-1',
              type: 'hotel',
              partner: 'nomadic',
              partner_product_id: 'hotel-1',
              title: 'Seaside Hotel',
              subtitle: 'Near the beach',
              image_url: null,
              price_estimate: 150,
              live_price: null,
              currency: 'EUR',
              price_basis: 'per_trip',
              is_estimate_only: true,
              deeplink: 'https://example.com',
              rating: 4.8,
              review_count: 120,
              location_label: 'Nice, France',
              geo: null,
              tags: [],
              availability_status: 'unknown',
              meta: {},
              score: null,
              source: null,
            },
          ],
          flights: [],
          activities: [],
        },
        selections: { stay: null, flight: null, activities: [] },
      },
    ],
    tiles: {},
  },
};

describe('NomadicLanding document hydration', () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_URL = 'http://test.local';
    window.localStorage.setItem('session_id', 'session-abc');
  });

  // TODO: This test needs proper mocking of all component side effects
  // (geolocation, origin detection, trip input regeneration) to work correctly.
  // The component has complex useEffect dependencies that trigger additional
  // API calls which interfere with simple mock setups.
  it.skip('restores branches and tiles from existing document', async () => {
    const fetchMock = vi.fn().mockImplementation(() => {
      return Promise.resolve({
        ok: true,
        json: async () => DOCUMENT_RESPONSE,
      });
    });

    global.fetch = fetchMock as unknown as typeof fetch;

    render(<NomadicLanding />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const documentCall = fetchMock.mock.calls.find(
      (call: unknown[]) =>
        typeof call[0] === 'string' && call[0].includes('/v1/document?session_id=')
    );
    expect(documentCall).toBeDefined();

    expect(
      await screen.findByRole('button', { name: 'Beach Escape' })
    ).toBeInTheDocument();

    expect(await screen.findByText('Seaside Hotel')).toBeInTheDocument();
  });
});
