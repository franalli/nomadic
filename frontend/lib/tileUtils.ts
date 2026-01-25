/**
 * Tile Utilities
 *
 * Helper functions for working with tiles.
 */

import type { Tile } from '@/types/tile';

/**
 * Check if tile type is a flight.
 */
export function isFlightType(type: string): boolean {
  const lower = type.toLowerCase();
  return lower.includes('flight') || lower === 'air';
}

/**
 * Check if tile type is a hotel/stay.
 */
export function isHotelType(type: string): boolean {
  const lower = type.toLowerCase();
  return lower.includes('hotel') || lower.includes('stay') || lower === 'accommodation';
}

/**
 * Check if tile type is an activity.
 */
export function isActivityType(type: string): boolean {
  const lower = type.toLowerCase();
  return (
    lower.includes('activity') ||
    lower.includes('experience') ||
    lower.includes('tour') ||
    lower === 'attraction'
  );
}

/**
 * Extract API parameters from tile for debug preview tooltip.
 * Shows the constructed params proving this isn't a hallucinated URL.
 *
 * Used in YC demo to show raw JSON payload on "Book" button hover.
 */
export function getDeepLinkParams(tile: Tile): Record<string, string | number | null> {
  const meta = tile.meta as Record<string, unknown> | undefined;

  // Build params based on tile type
  if (isFlightType(tile.type || '')) {
    return {
      type: 'flight',
      origin: (meta?.origin as string) || null,
      destination: (meta?.destination as string) || null,
      departure: (meta?.departure_date as string) || null,
      airline: (meta?.airline as string) || null,
      flight_id: tile.id,
    };
  }

  // Hotel/stay tiles
  if (isHotelType(tile.type || '')) {
    return {
      type: 'hotel',
      hotel_id: tile.id,
      location: tile.location_label || null,
      checkin: (meta?.checkin as string) || null,
      checkout: (meta?.checkout as string) || null,
      rooms: (meta?.rooms as number) || 1,
    };
  }

  // Activity tiles
  return {
    type: 'activity',
    activity_id: tile.id,
    location: tile.location_label || null,
    date: (meta?.date as string) || null,
  };
}
