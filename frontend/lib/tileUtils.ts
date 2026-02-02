/**
 * Tile Utilities
 *
 * Helper functions for working with tiles.
 */

import { isFlightType, isHotelType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

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
