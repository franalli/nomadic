import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

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
});
