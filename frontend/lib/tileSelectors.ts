/**
 * Tile Selectors
 *
 * Client-side grouping of tiles by type.
 * Keeps backend simple (Record<string, Tile>), groups for UI.
 */

import type { Tile } from '@/types/tile';

export interface TilesByType {
  hotels: Tile[];
  flights: Tile[];
  activities: Tile[];
}

/**
 * Group tiles by type - client-side selector.
 * Backend keeps tiles as Record<string, Tile>; this groups for tabbed UI.
 */
export function selectTilesByType(tiles: Record<string, Tile> | Tile[]): TilesByType {
  const result: TilesByType = { hotels: [], flights: [], activities: [] };

  const tileArray = Array.isArray(tiles) ? tiles : Object.values(tiles);

  for (const tile of tileArray) {
    const type = tile.type?.toLowerCase() || '';

    if (type.includes('hotel') || type.includes('stay') || type === 'accommodation') {
      result.hotels.push(tile);
    } else if (type.includes('flight')) {
      result.flights.push(tile);
    } else if (
      type.includes('activity') ||
      type.includes('experience') ||
      type.includes('tour') ||
      type.includes('attraction')
    ) {
      result.activities.push(tile);
    }
  }

  return result;
}

/**
 * Get total tile count across all categories.
 */
export function getTotalTileCount(tilesByType: TilesByType): number {
  return (
    tilesByType.hotels.length +
    tilesByType.flights.length +
    tilesByType.activities.length
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile Type Normalization
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Normalized tile category for consistent filtering.
 */
export type NormalizedTileCategory = 'hotel' | 'flight' | 'activity' | 'unknown';

/**
 * Normalization mappings for tile types.
 * Handles case variations, compound types, and synonyms.
 */
const TILE_TYPE_MAPPINGS: Record<string, NormalizedTileCategory> = {
  // Hotels/Stays
  hotel: 'hotel',
  stay: 'hotel',
  accommodation: 'hotel',
  lodging: 'hotel',
  resort: 'hotel',
  hostel: 'hotel',
  villa: 'hotel',
  apartment: 'hotel',
  // Flights
  flight: 'flight',
  air: 'flight',
  // Activities
  activity: 'activity',
  experience: 'activity',
  tour: 'activity',
  attraction: 'activity',
  excursion: 'activity',
  event: 'activity',
  ticket: 'activity',
};

/**
 * Normalize a tile type string to a standard category.
 *
 * Handles:
 * - Case variations: 'Activity', 'ACTIVITY', 'activity'
 * - Compound types: 'activity_tour', 'hotel-stay'
 * - Synonyms: 'experience' -> 'activity', 'stay' -> 'hotel'
 *
 * @example
 * normalizeTileType('Activity') // => 'activity'
 * normalizeTileType('HOTEL_STAY') // => 'hotel'
 * normalizeTileType('experience') // => 'activity'
 */
export function normalizeTileType(type: string | undefined | null): NormalizedTileCategory {
  if (!type) {
    console.warn('[normalizeTileType] Received null/undefined type');
    return 'unknown';
  }

  const lower = type.toLowerCase().trim();

  // Direct match
  if (lower in TILE_TYPE_MAPPINGS) {
    return TILE_TYPE_MAPPINGS[lower];
  }

  // Check for compound types (e.g., 'activity_tour', 'hotel-stay')
  const parts = lower.split(/[_\-\s]+/);
  for (const part of parts) {
    if (part in TILE_TYPE_MAPPINGS) {
      return TILE_TYPE_MAPPINGS[part];
    }
  }

  // Partial match (e.g., 'diving_activity' contains 'activity')
  for (const [key, category] of Object.entries(TILE_TYPE_MAPPINGS)) {
    if (lower.includes(key)) {
      return category;
    }
  }

  // DEBUG: Log unrecognized types to help identify missing mappings
  console.warn(`[normalizeTileType] Unknown type: "${type}" → "${lower}"`);
  return 'unknown';
}
