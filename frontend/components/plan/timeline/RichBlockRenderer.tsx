'use client';

/**
 * RichBlockRenderer
 *
 * Smart block renderer for S3 Itinerary View.
 * Routes to the appropriate component based on block type and state.
 *
 * Extracted from TimelineThread to reduce file size.
 * Layers (in priority order):
 *   1. Logistics (arrival/departure, check-in/check-out)
 *   2. Constraints (no_fly, rest_day, acclimatization)
 *   3. Booking integration (ghost slots)
 *   4. Activity (ActivityMiniCard)
 */

import { useMemo } from 'react';

import { placeholderImageForTile } from '@/lib/placeholders';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch } from '@/types/document';
import type { DayBlock } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { ActivityMiniCard } from './blocks/ActivityMiniCard';
import { GhostSlot } from './blocks/GhostSlot';
import { LogisticsBlock } from './blocks/LogisticsBlock';
import { SafetyBlock } from './blocks/SafetyBlock';
import { getDisplayTime } from './blocks/types';

export interface RichBlockRendererProps {
  block: DayBlock;
  blockIndex: number;
  blockId: string;
  dayNumber: number;
  /** Current view mode (planning vs booking) - controls Book button visibility */
  mode: 'planning' | 'booking';
  /** Set of saved tile IDs for booking state */
  savedTileIds?: Set<string>;
  /** Set of preferred tile IDs for attribution badges */
  preferredTileIds?: Set<string>;
  /** Callback to open booking drawer for a category */
  onOpenBookingDrawer?: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  /** Callback to unassign a booked tile from a block */
  onUnassignTile?: (blockId: string) => void;
  /** Callback to open stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
  /** Callback to open flights settings sheet */
  onOpenFlightsSettings?: () => void;
  /** Callback to remove a block from the itinerary */
  onRemoveBlock?: (blockId: string, dayNumber: number) => void;
  /** Stage 17: Day layout variant (compact = single-activity row) */
  variant?: 'default' | 'compact';
  /** Whether this block is map-highlighted (hovered on map) */
  isHighlighted?: boolean;
}

function normalizeText(value: string | undefined): string {
  return (value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function getTileImage(tile: Partial<Tile> | undefined): string | undefined {
  if (!tile) return undefined;
  return tile.image_url;
}

function isHotelTile(tile: Tile | undefined): boolean {
  if (!tile) return false;
  const tileType = (tile.type || '').toLowerCase();
  return tileType.includes('hotel') || tileType.includes('stay') || tileType.includes('accommodation');
}

function resolveSelectedStayTile(
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

function resolveHotelImage(
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

function resolveLogisticsImage(
  block: DayBlock,
  tiles: Record<string, Tile> | undefined
): string | undefined {
  const directImage = getTileImage(block.booked_tile) || block.image_url;
  if (directImage) return directImage;

  const bookedTileId = block.booked_tile?.id;
  if (!bookedTileId || !tiles) return undefined;
  return getTileImage(tiles[bookedTileId]);
}

export function RichBlockRenderer({
  block,
  blockIndex,
  blockId,
  dayNumber,
  mode,
  savedTileIds,
  preferredTileIds,
  onOpenBookingDrawer,
  onUnassignTile,
  onOpenStaysSettings,
  onOpenFlightsSettings,
  onRemoveBlock,
  variant,
  isHighlighted,
}: RichBlockRendererProps) {
  const tiles = useDocumentStore((state) => state.document?.tiles);
  const branches = useDocumentStore((state) => state.document?.branches);
  const selectedBranchId = useDocumentStore((state) => state.selectedBranchId);
  const selectedStayTile = useMemo(
    () => resolveSelectedStayTile(branches, selectedBranchId, tiles),
    [branches, selectedBranchId, tiles]
  );
  const resolvedHotelImage = useMemo(
    () => resolveHotelImage(block, tiles, selectedStayTile),
    [block, tiles, selectedStayTile]
  );
  const resolvedLogisticsImage = useMemo(
    () => resolveLogisticsImage(block, tiles),
    [block, tiles]
  );
  const resolvedHotelName = selectedStayTile?.title || block.hotel_name;
  const resolvedHotelDetails = block.logistics_details || selectedStayTile?.location_label;

  // 1. LOGISTICS LAYER - Hard times (arrival/departure/check-in/check-out)
  if (block.buffer_type === 'arrival' || block.buffer_type === 'departure') {
    return (
      <LogisticsBlock
        key={blockId}
        type={block.buffer_type}
        time={getDisplayTime(block, blockIndex)}
        details={block.logistics_details}
        hotelImage={resolvedLogisticsImage}
        onOpenFlightsSettings={onOpenFlightsSettings}
      />
    );
  }

  // Check-in/check-out blocks
  const activityLower = (block.activity_type || '').toLowerCase();
  if (activityLower.includes('check-in') || activityLower.includes('check in')) {
    return (
      <LogisticsBlock
        key={blockId}
        type="checkin"
        time={getDisplayTime(block, blockIndex)}
        hotelName={resolvedHotelName}
        hotelImage={resolvedHotelImage}
        details={resolvedHotelDetails}
        // Preference attribution for hotels
        preferenceStatus={block.preference_status}
        alternativeTileId={block.alternative_tile_id}
        onOpenStaysSettings={onOpenStaysSettings}
      />
    );
  }
  if (activityLower.includes('check-out') || activityLower.includes('check out')) {
    return (
      <LogisticsBlock
        key={blockId}
        type="checkout"
        time={getDisplayTime(block, blockIndex)}
        hotelName={resolvedHotelName}
        hotelImage={resolvedHotelImage}
        details={resolvedHotelDetails}
      />
    );
  }

  // 2. CONSTRAINT LAYER - Safety blocks (Red Zone)
  if (block.is_buffer && block.buffer_type === 'no_fly') {
    return (
      <SafetyBlock
        key={blockId}
        reason={block.buffer_reason || 'Surface interval required'}
        until={block.scheduled_time}
        type="no_fly"
      />
    );
  }

  // Other safety buffers (rest day, acclimatization)
  if (block.is_buffer || block.buffer_type === 'rest_day' || block.buffer_type === 'acclimatization') {
    return (
      <SafetyBlock
        key={blockId}
        reason={block.buffer_reason || 'Rest day recommended'}
        type={block.buffer_type as 'rest_day' | 'acclimatization' | undefined}
      />
    );
  }

  // 3. BOOKING INTEGRATION - Ghost slots for unbooked items
  if (block.requires_booking && !block.booked_tile) {
    return (
      <GhostSlot
        key={blockId}
        category={block.booking_category || 'activity'}
        context={block.booking_category === 'hotel' ? '3 Nights' : undefined}
        onSelect={() => onOpenBookingDrawer?.(block.booking_category || 'activity')}
      />
    );
  }

  // 4. ACTIVITY LAYER - Rich activity cards
  const isBooked = mode === 'booking'
    ? (!!block.booked_tile || !!(block.id && savedTileIds?.has(block.id)))
    : (block.preference_status === 'user_preferred' || !!(block.id && savedTileIds?.has(block.id)));

  // Compute preference status for attribution badge
  // Priority: 1) Backend-computed status (includes AI override), 2) Local preference check
  const tileId = block.booked_tile?.id;
  const isUserPreferred = tileId && preferredTileIds?.has(tileId);
  const preferenceStatus = block.preference_status
    ?? (isUserPreferred ? 'user_preferred' as const : undefined);

  return (
    <ActivityMiniCard
      key={blockId}
      block={block}
      displayTime={getDisplayTime(block, blockIndex)}
      isBooked={isBooked}
      // Only show Book button in booking mode
      onBook={mode === 'booking' && onOpenBookingDrawer
        ? () => onOpenBookingDrawer(block.booking_category || 'activity')
        : undefined}
      onUnassign={isBooked && block.id && onUnassignTile ? () => onUnassignTile(block.id!) : undefined}
      mode={mode}
      preferenceStatus={preferenceStatus}
      alternativeTileId={block.alternative_tile_id}
      // TODO: Wire up switch handler when we have tile replacement API
      onSwitchToAlternative={undefined}
      onRemove={onRemoveBlock && block.id ? () => onRemoveBlock(block.id!, dayNumber) : undefined}
      isRemovable={!block.is_buffer && !['arrival', 'departure', 'check-in', 'check-out'].includes(block.activity_type)}
      variant={variant}
      isHighlighted={isHighlighted}
    />
  );
}
