import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { RichBlockRenderer } from '@/components/plan/timeline/RichBlockRenderer';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DayBlock } from '@/types/plan-envelope';

function buildCheckInBlock(overrides: Partial<DayBlock> = {}): DayBlock {
  return {
    period: 'afternoon',
    activity_type: 'Check-in',
    summary: 'Settle into hotel',
    ...overrides,
  };
}

function buildArrivalBlock(overrides: Partial<DayBlock> = {}): DayBlock {
  return {
    period: 'morning',
    activity_type: 'Arrival',
    summary: 'Arrive at destination',
    buffer_type: 'arrival',
    ...overrides,
  };
}

describe('RichBlockRenderer check-in thumbnails', () => {
  beforeEach(() => {
    useDocumentStore.getState().reset();
  });

  it('uses block image when booked tile image is missing', () => {
    const block = buildCheckInBlock({
      hotel_name: 'Fallback Hotel',
      image_url: 'https://images.unsplash.com/photo-fallback-test?w=64&h=64&fit=crop',
      booked_tile: {
        id: 'hotel_1',
        type: 'hotel',
        title: 'Fallback Hotel',
        currency: 'USD',
        deeplink_url: 'https://example.com/hotel_1',
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="checkin-1"
        dayNumber={1}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /fallback hotel/i });
    expect(img).toHaveAttribute('src', block.image_url);
  });

  it('falls back to placeholder when check-in image fails to load', () => {
    const block = buildCheckInBlock({
      hotel_name: 'Broken Hotel',
      image_url: 'https://images.unsplash.com/photo-broken-test?w=64&h=64&fit=crop',
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="checkin-2"
        dayNumber={1}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /broken hotel/i });
    fireEvent.error(img);

    const fallbackImg = screen.getByRole('img', { name: /broken hotel/i });
    expect(fallbackImg).toHaveAttribute('src');
    expect(fallbackImg.getAttribute('src')).toContain('images.unsplash.com');
  });

  it('falls back to icon only if both primary and placeholder images fail', () => {
    const block = buildCheckInBlock({
      hotel_name: 'Double Broken Hotel',
      image_url: 'https://images.unsplash.com/photo-broken-test-2?w=64&h=64&fit=crop',
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="checkin-2b"
        dayNumber={1}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /double broken hotel/i });
    fireEvent.error(img);
    const placeholderImg = screen.getByRole('img', { name: /double broken hotel/i });
    fireEvent.error(placeholderImg);

    expect(screen.queryByRole('img', { name: /double broken hotel/i })).not.toBeInTheDocument();
    expect(screen.getByText('Check-in')).toBeInTheDocument();
  });

  it('hydrates hotel image from document tiles when block has no image fields', () => {
    useDocumentStore.setState((state) => ({
      document: state.document
        ? {
          ...state.document,
          tiles: {
            ...state.document.tiles,
            hotel_42: {
              id: 'hotel_42',
              type: 'hotel',
              title: 'Hydrated Hotel',
              image_url: 'https://images.unsplash.com/photo-hydrated-test?w=64&h=64&fit=crop',
              currency: 'USD',
              deeplink_url: 'https://example.com/hotel_42',
            },
          },
        }
        : {
          trip_inputs: { ...DEFAULT_TRIP_INPUTS },
          branches: [],
          tiles: {
            hotel_42: {
              id: 'hotel_42',
              type: 'hotel',
              title: 'Hydrated Hotel',
              image_url: 'https://images.unsplash.com/photo-hydrated-test?w=64&h=64&fit=crop',
              currency: 'USD',
              deeplink_url: 'https://example.com/hotel_42',
            },
          },
        },
    }));

    const block = buildCheckInBlock({
      hotel_name: 'Hydrated Hotel',
      booked_tile: {
        id: 'hotel_42',
        type: 'hotel',
        title: 'Hydrated Hotel',
        currency: 'USD',
        deeplink_url: 'https://example.com/hotel_42',
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="checkin-3"
        dayNumber={1}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /hydrated hotel/i });
    expect(img).toHaveAttribute(
      'src',
      'https://images.unsplash.com/photo-hydrated-test?w=64&h=64&fit=crop'
    );
  });

  it('uses selected stay tile for check-in when block hotel differs from stays selection', () => {
    useDocumentStore.setState({
      selectedBranchId: 'branch_1',
      document: {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS },
        branches: [
          {
            id: 'branch_1',
            label: 'Primary',
            description: 'Primary option',
            is_primary: true,
            tiles: {
              stays: ['hotel_selected', 'hotel_outdated'],
              flights: [],
              activities: [],
            },
            selections: {
              stay: 'hotel_selected',
              flight: null,
              activities: [],
            },
          },
        ],
        tiles: {
          hotel_selected: {
            id: 'hotel_selected',
            type: 'hotel',
            title: 'Correct Stay',
            image_url: 'https://images.unsplash.com/photo-correct-stay?w=64&h=64&fit=crop',
            location_label: 'Canal district, Amsterdam',
            currency: 'USD',
            deeplink_url: 'https://example.com/hotel_selected',
          },
          hotel_outdated: {
            id: 'hotel_outdated',
            type: 'hotel',
            title: 'Outdated Stay',
            image_url: 'https://images.unsplash.com/photo-outdated-stay?w=64&h=64&fit=crop',
            currency: 'USD',
            deeplink_url: 'https://example.com/hotel_outdated',
          },
        },
      },
    });

    const block = buildCheckInBlock({
      hotel_name: 'Outdated Stay',
      booked_tile: {
        id: 'hotel_outdated',
        type: 'hotel',
        title: 'Outdated Stay',
        image_url: 'https://images.unsplash.com/photo-outdated-stay?w=64&h=64&fit=crop',
        currency: 'USD',
        deeplink_url: 'https://example.com/hotel_outdated',
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="checkin-selected-stay"
        dayNumber={1}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /correct stay/i });
    expect(img).toHaveAttribute(
      'src',
      'https://images.unsplash.com/photo-correct-stay?w=64&h=64&fit=crop'
    );
    expect(screen.getByText('Correct Stay')).toBeInTheDocument();
    expect(screen.queryByText('Outdated Stay')).not.toBeInTheDocument();
  });

  it('keeps flight icon fallback when arrival has no image', () => {
    const block = buildArrivalBlock();

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="arrival-1"
        dayNumber={1}
        mode="planning"
      />
    );

    expect(screen.queryByRole('img', { name: /arrival/i })).not.toBeInTheDocument();
    expect(screen.getByText('Arrival')).toBeInTheDocument();
  });

  it('renders a flight deeplink CTA for arrival blocks with a booked flight', () => {
    const block = buildArrivalBlock({
      booked_tile: {
        id: 'flight_1',
        type: 'flight',
        title: 'ITA Airways - Direct',
        currency: 'USD',
        deeplink_url: 'https://www.aviasales.com/search/AMS0704FCO14041',
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="arrival-flight-link"
        dayNumber={1}
        mode="planning"
      />
    );

    expect(screen.getByRole('link', { name: /book on aviasales/i })).toHaveAttribute(
      'href',
      'https://www.aviasales.com/search/AMS0704FCO14041'
    );
  });
});

describe('RichBlockRenderer activity hierarchy', () => {
  beforeEach(() => {
    useDocumentStore.getState().reset();
  });

  function buildActivityBlock(overrides: Partial<DayBlock> = {}): DayBlock {
    return {
      period: 'afternoon',
      activity_type: 'roman forum',
      summary: 'Roman Forum',
      map_type: 'cultural',
      rating: 4.8,
      review_count: 142000,
      price_estimate: 60,
      duration: '2h',
      intensity: 'light',
      ...overrides,
    };
  }

  it('renders title before supporting metadata', () => {
    const block = buildActivityBlock();
    const { container } = render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-1"
        dayNumber={2}
        mode="planning"
      />
    );

    expect(screen.getByText('Roman Forum')).toBeInTheDocument();
    const text = (container.textContent ?? '').toLowerCase();
    expect(text.indexOf('roman forum')).toBeLessThan(text.indexOf('4.8'));
    expect(text).toContain('2h');
    expect(text).toContain('~$60');
  });

  it('shows category before time-context metadata', () => {
    const block = buildActivityBlock();
    const { container } = render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-2"
        dayNumber={2}
        mode="planning"
      />
    );

    expect(screen.getByText('CULTURAL')).toBeInTheDocument();
    const text = container.textContent ?? '';
    expect(text.indexOf('CULTURAL')).toBeLessThan(text.indexOf('AFTERNOON'));
  });

  it('keeps tours category distinct from cultural', () => {
    const block = buildActivityBlock({
      map_type: 'tours',
    });
    const { container } = render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-2b"
        dayNumber={2}
        mode="planning"
      />
    );

    expect(screen.getByText('TOURS')).toBeInTheDocument();
    expect(screen.queryByText('CULTURAL')).not.toBeInTheDocument();
    const text = container.textContent ?? '';
    expect(text.indexOf('TOURS')).toBeLessThan(text.indexOf('AFTERNOON'));
  });

  it('keeps cultural-attraction category under cultural', () => {
    const block = buildActivityBlock({
      map_type: 'cultural_attraction',
    });
    const { container } = render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-2c"
        dayNumber={2}
        mode="planning"
      />
    );

    expect(screen.getByText('CULTURAL')).toBeInTheDocument();
    expect(screen.queryByText('TOURS')).not.toBeInTheDocument();
    const text = container.textContent ?? '';
    expect(text.indexOf('CULTURAL')).toBeLessThan(text.indexOf('AFTERNOON'));
  });

  it('maps bare attraction category to tours', () => {
    const block = buildActivityBlock({
      map_type: 'attraction',
    });
    const { container } = render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-2d"
        dayNumber={2}
        mode="planning"
      />
    );

    expect(screen.getByText('TOURS')).toBeInTheDocument();
    expect(screen.queryByText('CULTURAL')).not.toBeInTheDocument();
    const text = container.textContent ?? '';
    expect(text.indexOf('TOURS')).toBeLessThan(text.indexOf('AFTERNOON'));
  });

  it('falls back to booked_tile image when block image is missing or invalid', () => {
    const block = buildActivityBlock({
      image_url: 'https://example.invalid/not-allowed.jpg',
      booked_tile: {
        id: 'activity_tile_1',
        type: 'activity',
        title: 'Roman Forum',
        image_url: 'https://images.unsplash.com/photo-fallback-activity?w=80&h=80&fit=crop',
        currency: 'USD',
        deeplink_url: 'https://example.com/activity_tile_1',
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-3"
        dayNumber={2}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /roman forum/i });
    expect(img).toHaveAttribute('src');
    expect(img.getAttribute('src')).toContain('photo-fallback-activity');
  });

  it('prefers proxied Google Places photo when photo_name is available', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          url: '/api/media/google-places-photo?name=places%2FChIJx%2Fphotos%2FAbCd_123&max_width=320&max_height=240&exp=123&sig=testsig',
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }
      )
    );

    const block = buildActivityBlock({
      image_url: 'https://images.unsplash.com/photo-placeholder-activity?w=80&h=80&fit=crop',
      booked_tile: {
        id: 'activity_tile_google_1',
        type: 'activity',
        title: 'Roman Forum',
        image_url: 'https://images.unsplash.com/photo-placeholder-activity?w=80&h=80&fit=crop',
        currency: 'USD',
        deeplink_url: 'https://example.com/activity_tile_google_1',
        meta: {
          photo_name: 'places/ChIJx/photos/AbCd_123',
        },
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-4"
        dayNumber={2}
        mode="planning"
      />
    );

    const img = screen.getByRole('img', { name: /roman forum/i });
    await waitFor(() => {
      expect(img).toHaveAttribute('src');
      expect(img.getAttribute('src')).toContain('/api/media/google-places-photo?');
      expect(img.getAttribute('src')).toContain('sig=testsig');
    });
  });

  it('normalizes duration format and falls back price label from booked tile metadata', () => {
    const block = buildActivityBlock({
      duration: '2.5 hours',
      price_level: undefined,
      price_estimate: undefined,
      booked_tile: {
        id: 'activity_tile_5',
        type: 'activity',
        title: 'Roman Forum',
        currency: 'USD',
        deeplink_url: 'https://example.com/activity_tile_5',
        meta: {
          price_estimate: '$$',
        },
      },
    });

    render(
      <RichBlockRenderer
        block={block}
        blockIndex={0}
        blockId="activity-5"
        dayNumber={2}
        mode="planning"
      />
    );

    expect(screen.getByText('2.5h')).toBeInTheDocument();
    expect(screen.getByText('$$')).toBeInTheDocument();
  });
});
