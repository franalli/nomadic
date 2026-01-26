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
// Individual tile type discriminators
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Check if a tile is a stay/hotel tile.
 * Matches 'hotel', 'stay', 'accommodation' in type field.
 */
function isStayTile(tile: Tile): boolean {
  const type = tile.type?.toLowerCase() ?? '';
  return type.includes('hotel') || type.includes('stay') || type === 'accommodation';
}

/**
 * Check if a tile is a flight tile.
 */
function isFlightTile(tile: Tile): boolean {
  const type = tile.type?.toLowerCase() || '';
  return type.includes('flight');
}

/**
 * Check if a tile is an activity tile.
 */
function isActivityTile(tile: Tile): boolean {
  const type = tile.type?.toLowerCase() || '';
  return (
    type.includes('activity') ||
    type.includes('experience') ||
    type.includes('tour') ||
    type.includes('attraction')
  );
}

/**
 * Filter tiles by category type.
 * Returns array of tiles matching the specified category.
 */
export function filterTilesByType(
  tiles: Record<string, Tile> | Tile[],
  category: 'stay' | 'flight' | 'activity'
): Tile[] {
  const tileArray = Array.isArray(tiles) ? tiles : Object.values(tiles);

  switch (category) {
    case 'stay':
      return tileArray.filter(isStayTile);
    case 'flight':
      return tileArray.filter(isFlightTile);
    case 'activity':
      return tileArray.filter(isActivityTile);
  }
}
