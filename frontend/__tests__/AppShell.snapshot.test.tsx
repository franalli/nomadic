import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppShell } from '../components/layout/AppShell';

const SNAPSHOT_RESPONSE = {
  branches: [
    {
      id: 1,
      label: 'Beach Escape',
      description: 'Relax on the coast',
      destination: 'Nice',
    },
  ],
  primary_branch_id: 1,
  tiles: [],
  trip_context: {
    id: 99,
    origin: 'AMS',
    destination_hint: 'Europe',
    start_date: '2025-06-01',
    end_date: '2025-06-10',
    budget_bucket: 'mid',
    group_size: 2,
    vibes: ['foodie'],
    raw_prompt: 'Need a trip',
  },
};

const TILE_SEARCH_RESPONSE = {
  tiles: [
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
      deeplink_url: 'https://example.com',
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
  tiles_request_id: 'req-1',
};

describe('AppShell snapshot hydration', () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_URL = 'http://test.local';
    window.localStorage.setItem('session_id', 'session-abc');
  });

  it('restores branches and fetches tiles when snapshot has none', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => SNAPSHOT_RESPONSE })
      .mockResolvedValueOnce({ ok: true, json: async () => TILE_SEARCH_RESPONSE });

    global.fetch = fetchMock as unknown as typeof fetch;

    render(<AppShell />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toContain('/v1/session/snapshot');

    expect(
      await screen.findByRole('button', { name: 'Beach Escape' })
    ).toBeInTheDocument();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const searchCall = fetchMock.mock.calls[1];
    expect(searchCall[0]).toBe(`${process.env.NEXT_PUBLIC_API_URL}/v1/tiles/search`);
    expect(searchCall[1]).toMatchObject({ method: 'POST' });

    expect(await screen.findByText('Seaside Hotel')).toBeInTheDocument();
  });
});
