import { act, fireEvent, render, screen } from '@testing-library/react';
import type { ImgHTMLAttributes } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SuggestionCardCompact } from '@/components/plan/tiles/suggestionCardSections';
import { TileCard } from '@/components/tiles/TileCard';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

vi.mock('next/image', () => ({
  default: ({
    alt,
    fill: _fill,
    priority: _priority,
    ...props
  }: ImgHTMLAttributes<HTMLImageElement> & { fill?: boolean; priority?: boolean }) => (
    <img alt={alt} {...props} />
  ),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    apiFetch: vi.fn().mockResolvedValue(new Response('{}', { status: 200 })),
    trackDeeplinkClick: vi.fn(),
  };
});

function buildTile(overrides: Partial<Tile> = {}): Tile {
  return {
    id: 'tile_1',
    type: 'hotel',
    title: 'Canal House',
    subtitle: 'Amsterdam Center',
    currency: 'USD',
    deeplink_url: 'https://www.booking.com/searchresults.html?ss=Canal+House',
    image_url: 'https://images.example.com/canal-house.jpg',
    price_estimate: 240,
    location_label: 'Amsterdam Center',
    rating: 4.8,
    is_refundable: true,
    meta: {
      amenities: [],
    },
    ...overrides,
  };
}

describe('SuggestionCardCompact sizing', () => {
  beforeEach(() => {
    act(() => {
      useDocumentStore.getState().reset();
      useDocumentStore.setState({
        version: 1,
        document: {
          trip_context_id: null,
          trip_inputs: {
            ...DEFAULT_TRIP_INPUTS,
            destination: 'Bali',
            start_date: '2026-04-01',
            end_date: '2026-04-07',
            adults: 1,
            children: 0,
          },
          branches: [],
          tiles: {},
          plan_view_state: 'S3_ITINERARY_READY',
        },
        updatedBy: null,
        updatedAt: null,
        isCommitting: false,
        error: null,
      });
    });
  });

  afterEach(() => {
    act(() => {
      useDocumentStore.getState().reset();
    });
  });

  it('gives hotel thumbnails more visual weight than the default compact size', () => {
    render(<SuggestionCardCompact tile={buildTile()} isSaved={false} />);

    const image = screen.getByRole('img', { name: 'Canal House' });
    const container = image.parentElement;

    expect(container).toHaveClass('h-16', 'w-24', 'rounded-xl');
    expect(image).toHaveAttribute('sizes', '96px');
  });

  it('uses a larger 48px badge container for compact flight cards', () => {
    render(
      <SuggestionCardCompact
        tile={buildTile({
          id: 'flight_1',
          type: 'flight',
          title: 'Emirates - 1 stop',
          image_url: 'https://images.example.com/emirates.png',
        })}
        isSaved={false}
      />
    );

    const image = screen.getByRole('img', { name: 'Emirates - 1 stop' });
    const container = image.parentElement;

    expect(container).toHaveClass('h-12', 'w-12', 'rounded-xl');
    expect(image).toHaveClass('h-9', 'w-9', 'object-contain');
    expect(image).toHaveAttribute('sizes', '48px');
  });

  it('recomputes Booking.com hrefs when the store trip dates change', () => {
    render(
      <SuggestionCardCompact
        tile={buildTile({
          title: 'The Ritz-Carlton Bali',
          deeplink_url:
            'https://www.booking.com/searchresults.html?ss=The+Ritz-Carlton+Bali&checkin=2026-04-01&checkout=2026-04-07&group_adults=1&group_children=0&no_rooms=1',
        })}
        isSaved={false}
      />
    );

    const bookingLink = screen.getByRole('link', { name: /book on booking\.com/i });
    let effectiveUrl = new URL(bookingLink.getAttribute('href') ?? '');

    expect(effectiveUrl.searchParams.get('checkin')).toBe('2026-04-01');
    expect(effectiveUrl.searchParams.get('checkout')).toBe('2026-04-07');

    act(() => {
      const current = useDocumentStore.getState().document;
      useDocumentStore.setState({
        document: current
          ? {
              ...current,
              trip_inputs: {
                ...current.trip_inputs,
                end_date: '2026-04-17',
                trip_duration: 17,
              },
            }
          : current,
      });
    });

    effectiveUrl = new URL(bookingLink.getAttribute('href') ?? '');
    expect(effectiveUrl.searchParams.get('checkin')).toBe('2026-04-01');
    expect(effectiveUrl.searchParams.get('checkout')).toBe('2026-04-17');
  });

  it('opens TileCard booking links with the updated Booking.com checkout date', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);

    render(
      <TileCard
        tile={buildTile({
          title: 'The Ritz-Carlton Bali',
          deeplink_url:
            'https://www.booking.com/searchresults.html?ss=The+Ritz-Carlton+Bali&checkin=2026-04-01&checkout=2026-04-07&group_adults=1&group_children=0&no_rooms=1',
        })}
      />
    );

    act(() => {
      const current = useDocumentStore.getState().document;
      useDocumentStore.setState({
        document: current
          ? {
              ...current,
              trip_inputs: {
                ...current.trip_inputs,
                end_date: '2026-04-17',
                trip_duration: 17,
              },
            }
          : current,
      });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Details' }));

    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy.mock.calls[0]?.[0]).toContain('checkout=2026-04-17');
    openSpy.mockRestore();
  });

  it('still refreshes TileCard Booking.com links when trip inputs are missing traveler counts', () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null);

    render(
      <TileCard
        tile={buildTile({
          title: 'The Ritz-Carlton Bali',
          deeplink_url:
            'https://www.booking.com/searchresults.html?ss=The+Ritz-Carlton+Bali&checkin=2026-04-01&checkout=2026-04-07&group_adults=1&group_children=0&no_rooms=1',
        })}
      />
    );

    act(() => {
      const current = useDocumentStore.getState().document;
      useDocumentStore.setState({
        document: current
          ? {
              ...current,
              trip_inputs: {
                ...current.trip_inputs,
                end_date: '2026-04-17',
                trip_duration: 17,
                adults: null,
                children: null,
              },
            }
          : current,
      });
    });

    fireEvent.click(screen.getByRole('button', { name: 'Details' }));

    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy.mock.calls[0]?.[0]).toContain('checkout=2026-04-17');
    expect(openSpy.mock.calls[0]?.[0]).toContain('group_adults=1');
    openSpy.mockRestore();
  });
});
