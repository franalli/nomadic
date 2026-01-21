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
