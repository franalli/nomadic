'use client';

/** RichBlockRenderer - Smart block renderer for S3 Itinerary View. */

import { useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useDocumentStore } from '@/state/documentStore';
import type { DayBlock } from '@/types/plan-envelope';

import { ActivityMiniCard } from './blocks/ActivityMiniCard';
import { GhostSlot } from './blocks/GhostSlot';
import { LogisticsBlock } from './blocks/LogisticsBlock';
import { SafetyBlock } from './blocks/SafetyBlock';
import { getDisplayTime } from './blocks/types';
import {
  getTileLinkLabel,
  resolveHotelImage,
  resolveLogisticsImage,
  resolveSelectedStayTile,
  resolveTileFromDocument,
} from './richBlockHelpers';

export interface RichBlockRendererProps {
  block: DayBlock;
  blockIndex: number;
  blockId: string;
  dayNumber: number;
  mode: 'planning' | 'booking';
  savedTileIds?: Set<string>;
  preferredTileIds?: Set<string>;
  onOpenBookingDrawer?: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onUnassignTile?: (blockId: string) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  onRemoveBlock?: (blockId: string, dayNumber: number) => void;
  isHighlighted?: boolean;
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
  isHighlighted,
}: RichBlockRendererProps) {
  const { tiles, branches } = useDocumentStore(
    useShallow((state) => ({ tiles: state.document?.tiles, branches: state.document?.branches }))
  );
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
  const resolvedLogisticsTile = useMemo(
    () => resolveTileFromDocument(block.booked_tile, tiles),
    [block.booked_tile, tiles]
  );
  const resolvedHotelName = selectedStayTile?.title || block.hotel_name;
  const resolvedHotelDetails = block.logistics_details || selectedStayTile?.location_label;
  const logisticsLinkLabel = useMemo(
    () => getTileLinkLabel(resolvedLogisticsTile),
    [resolvedLogisticsTile]
  );

  // 1. LOGISTICS LAYER
  if (block.buffer_type === 'arrival' || block.buffer_type === 'departure') {
    return (
      <LogisticsBlock
        key={blockId}
        type={block.buffer_type}
        time={getDisplayTime(block, blockIndex)}
        details={block.logistics_details}
        hotelImage={resolvedLogisticsImage}
        deeplinkLabel={logisticsLinkLabel}
        onOpenFlightsSettings={onOpenFlightsSettings}
        deeplinkUrl={resolvedLogisticsTile?.deeplink_url}
      />
    );
  }

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

  // 2. CONSTRAINT LAYER
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

  if (block.is_buffer || block.buffer_type === 'rest_day' || block.buffer_type === 'acclimatization') {
    return (
      <SafetyBlock
        key={blockId}
        reason={block.buffer_reason || 'Rest day recommended'}
        type={block.buffer_type as 'rest_day' | 'acclimatization' | undefined}
      />
    );
  }

  // 3. BOOKING INTEGRATION
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

  // 4. ACTIVITY LAYER
  const blockTitle = block.summary || block.booked_tile?.title;
  if (!blockTitle && !block.activity_type && !block.is_buffer) {
    return null;
  }

  const isBooked = mode === 'booking'
    ? (!!block.booked_tile || !!(block.id && savedTileIds?.has(block.id)))
    : (block.preference_status === 'user_preferred' || !!(block.id && savedTileIds?.has(block.id)));

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
      onBook={mode === 'booking' && onOpenBookingDrawer
        ? () => onOpenBookingDrawer(block.booking_category || 'activity')
        : undefined}
      onUnassign={isBooked && block.id && onUnassignTile ? () => onUnassignTile(block.id!) : undefined}
      mode={mode}
      preferenceStatus={preferenceStatus}
      alternativeTileId={block.alternative_tile_id}
      onSwitchToAlternative={undefined}
      onRemove={onRemoveBlock && block.id ? () => onRemoveBlock(block.id!, dayNumber) : undefined}
      isRemovable={!block.is_buffer && !['arrival', 'departure', 'check-in', 'check-out'].includes(block.activity_type)}
      isHighlighted={isHighlighted}
    />
  );
}
