import { getTileDeeplinkActionLabel } from '@/components/tiles/tileHelpers';
import { placeholderImageForTile } from '@/lib/placeholders';
import type { DocumentBranch } from '@/types/document';
import type { DayBlock } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

export function normalizeText(value: string | undefined): string {
  return (value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export function getTileImage(tile: Partial<Tile> | undefined): string | undefined {
  if (!tile) return undefined;
  return tile.image_url;
}

export function resolveTileFromDocument(
  tile: Partial<Tile> | undefined,
  tiles: Record<string, Tile> | undefined
): Partial<Tile> | undefined {
  if (!tile) return undefined;
  const hydrated = tile.id ? tiles?.[tile.id] : undefined;
  if (!hydrated) return tile;
  return {
    ...hydrated,
    ...tile,
    deeplink_url: tile.deeplink_url ?? hydrated.deeplink_url,
    image_url: tile.image_url ?? hydrated.image_url,
    title: tile.title ?? hydrated.title,
    type: tile.type ?? hydrated.type,
  };
}

export function getTileLinkLabel(tile: Partial<Tile> | undefined): string | undefined {
  if (!tile?.deeplink_url || tile.deeplink_url === '#' || !tile.type) return undefined;
  return getTileDeeplinkActionLabel({
    deeplink_url: tile.deeplink_url,
    type: tile.type,
  });
}

export function isHotelTile(tile: Tile | undefined): boolean {
  if (!tile) return false;
  const tileType = (tile.type || '').toLowerCase();
  return tileType.includes('hotel') || tileType.includes('stay') || tileType.includes('accommodation');
}

export function resolveSelectedStayTile(
  branches: DocumentBranch[] | undefined,
  selectedBranchId: string | null,
  tiles: Record<string, Tile> | undefined
): Tile | undefined {
  if (!branches || !tiles) return undefined;

  const selectedBranch =
    (selectedBranchId ? branches.find((branch) => branch.id === selectedBranchId) : undefined)
    ?? branches.find((branch) => branch.is_primary)
    ?? branches[0];

  const selectedStayId = selectedBranch?.selections?.stay;
  if (!selectedStayId) return undefined;

  const selectedStayTile = tiles[selectedStayId];
  return isHotelTile(selectedStayTile) ? selectedStayTile : undefined;
}

export function resolveHotelImage(
  block: DayBlock,
  tiles: Record<string, Tile> | undefined,
  selectedStayTile?: Tile
): string {
  const directImage = getTileImage(selectedStayTile) || getTileImage(block.booked_tile) || block.image_url;
  if (directImage) return directImage;

  const bookedTileId = selectedStayTile?.id || block.booked_tile?.id;
  if (bookedTileId && tiles?.[bookedTileId]) {
    const imageById = getTileImage(tiles[bookedTileId]);
    if (imageById) return imageById;
  }

  const targetTitle = normalizeText(selectedStayTile?.title || block.booked_tile?.title || block.hotel_name || '');
  if (!tiles) {
    return placeholderImageForTile({
      id: selectedStayTile?.id || block.booked_tile?.id || block.hotel_name || block.id || 'timeline-hotel',
      type: 'hotel',
    });
  }

  const hotelTiles = Object.values(tiles).filter((tile) => {
    const tileType = (tile.type || '').toLowerCase();
    return tileType.includes('hotel') || tileType.includes('stay') || tileType.includes('accommodation');
  });

  if (targetTitle) {
    for (const tile of hotelTiles) {
      const tileTitle = normalizeText(tile.title);
      if (!tileTitle) continue;
      const isTitleMatch =
        tileTitle === targetTitle || tileTitle.includes(targetTitle) || targetTitle.includes(tileTitle);
      if (!isTitleMatch) continue;

      const titleMatchImage = getTileImage(tile);
      if (titleMatchImage) return titleMatchImage;
    }
  }

  if (hotelTiles.length === 1) {
    const singleHotelImage = getTileImage(hotelTiles[0]);
    if (singleHotelImage) {
      return singleHotelImage;
    }
  }

  return placeholderImageForTile({
    id: selectedStayTile?.id || block.booked_tile?.id || block.hotel_name || block.id || 'timeline-hotel',
    type: 'hotel',
  });
}

export function resolveLogisticsImage(
  block: DayBlock,
  tiles: Record<string, Tile> | undefined
): string | undefined {
  const directImage = getTileImage(block.booked_tile) || block.image_url;
  if (directImage) return directImage;

  const bookedTileId = block.booked_tile?.id;
  if (!bookedTileId || !tiles) return undefined;
  return getTileImage(tiles[bookedTileId]);
}
