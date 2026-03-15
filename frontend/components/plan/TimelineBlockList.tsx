'use client';

import { Fragment, type ReactNode } from 'react';

import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { RichBlockRenderer } from './timeline/RichBlockRenderer';
import { filterBlocks } from './TimelineBlockList.helpers';
import { TimelineBlockListAddActivityButton } from './TimelineBlockListAddActivityButton';
import { TimelineBlockListFreeDay } from './TimelineBlockListFreeDay';
import { TimelineBlockListLegacyBlock } from './TimelineBlockListLegacyBlock';
import { computeBufferExclusions } from './useTimelineBufferLogic';

export interface TimelineBlockListProps {
  card: DayCard;
  useRichBlocks: boolean;
  activeBlockId?: string | null;
  showPriceEstimates: boolean;
  mode: 'planning' | 'booking';
  savedTileIds?: Set<string>;
  preferredTileIds?: Set<string>;
  onOpenBookingDrawer?: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onUnassignTile?: (blockId: string) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  onRemoveBlock?: (blockId: string, dayNumber: number) => void;
  blockWrapper?: (block: DayBlock, dayNumber: number, children: ReactNode) => ReactNode;
  dayWrapper?: (dayNumber: number, children: ReactNode) => ReactNode;
  freeDayDropSlot?: (dayNumber: number) => ReactNode;
  destination: string | null;
  categories: string[] | undefined;
  fillingDay: number | null;
  fillDayRejection: { dayNumber: number; reason: string } | null;
  handleFillDay: (dayNumber: number, dayDate: string | null, categories?: string[]) => Promise<void>;
  disableFillDayActions: boolean;
  onBrowse: (dayNumber: number, date: string | null) => void;
}

export function TimelineBlockList({
  card,
  useRichBlocks,
  activeBlockId,
  showPriceEstimates,
  mode,
  savedTileIds,
  preferredTileIds,
  onOpenBookingDrawer,
  onUnassignTile,
  onOpenStaysSettings,
  onOpenFlightsSettings,
  onRemoveBlock,
  blockWrapper,
  dayWrapper,
  freeDayDropSlot,
  destination,
  categories,
  fillingDay,
  fillDayRejection,
  handleFillDay,
  disableFillDayActions,
  onBrowse,
}: TimelineBlockListProps) {
  const applyBlockWrapper = blockWrapper ?? ((_b: DayBlock, _d: number, children: ReactNode) => children);
  const applyDayWrapper = dayWrapper ?? ((_d: number, children: ReactNode) => children);
  const blocksToRender = useRichBlocks ? filterBlocks(card.blocks) : card.blocks;
  const bufferBlocks = blocksToRender.filter(
    (block) => block.is_buffer && block.buffer_type !== 'arrival' && block.buffer_type !== 'departure'
  );
  const contentBlocks = blocksToRender.filter((block) => !block.is_buffer);
  const isArrival = card.blocks.some((block) => block.buffer_type === 'arrival');
  const isDeparture = card.blocks.some((block) => block.buffer_type === 'departure');
  const hasOnlyFreeDay = contentBlocks.length === 1 && contentBlocks[0].activity_type === 'free_day';
  const isFreeDay =
    useRichBlocks &&
    !isArrival &&
    !isDeparture &&
    (contentBlocks.length === 0 || hasOnlyFreeDay);
  const { chipsToShow, isConstraintBuffer } = computeBufferExclusions(bufferBlocks, categories);

  const blocksContainer = (
    <div className="space-y-4 pl-[52px]">
      {isFreeDay ? (
        <TimelineBlockListFreeDay
          dayNumber={card.day_number}
          date={card.date}
          bufferBlocks={bufferBlocks}
          destination={destination}
          chipsToShow={chipsToShow}
          isConstraintBuffer={isConstraintBuffer}
          fillingDay={fillingDay}
          disableFillDayActions={disableFillDayActions}
          fillDayRejection={fillDayRejection}
          onFillDay={handleFillDay}
          onBrowse={onBrowse}
          freeDayDropSlot={freeDayDropSlot?.(card.day_number)}
        />
      ) : (
        blocksToRender.map((block, filteredIndex) => {
          const originalIndex = card.blocks.indexOf(block);
          const blockIndex = originalIndex !== -1 ? originalIndex : filteredIndex;
          const blockId = block.id || `block-${card.day_number}-${blockIndex}`;

          if (block.is_skeleton) {
            return (
              <div
                key={`skeleton-${card.day_number}-${blockIndex}`}
                className="rounded-xl border border-dashed border-zinc-200/50 bg-zinc-100/10 p-4 opacity-60 dark:border-white/10 dark:bg-white/[0.03]"
              >
                <div className="flex items-start gap-2">
                  <div className="h-8 w-8 flex-shrink-0 animate-pulse rounded-full bg-zinc-200/50 dark:bg-zinc-700/50" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-24 animate-pulse rounded bg-zinc-200/50 dark:bg-zinc-700/50" />
                    <div className="h-3 w-48 animate-pulse rounded bg-zinc-200/50 dark:bg-zinc-700/50" />
                  </div>
                </div>
                <p className="mt-3 text-center text-xs text-zinc-500 dark:text-zinc-400">
                  Planning Day {card.day_number}...
                </p>
              </div>
            );
          }

          if (useRichBlocks) {
            const isActiveBlock = activeBlockId === blockId;
            const richBlockInner = (
              <div
                id={`timeline-item-${blockId}`}
                data-map-id={blockId}
                onMouseEnter={() => useUIStore.getState().setHoveredActivityId(blockId)}
                onMouseLeave={() => useUIStore.getState().setHoveredActivityId(null)}
                className={cn(
                  'transition-all duration-300',
                  isActiveBlock && 'rounded-xl ring-2 ring-emerald-500 ring-offset-2 ring-offset-white dark:ring-offset-zinc-950 scale-[1.01]',
                  '[&[data-map-hovered=true]]:ring-1 [&[data-map-hovered=true]]:ring-blue-400/60 [&[data-map-hovered=true]]:rounded-xl'
                )}
              >
                <RichBlockRenderer
                  block={block}
                  blockIndex={blockIndex}
                  blockId={blockId}
                  dayNumber={card.day_number}
                  mode={mode}
                  savedTileIds={savedTileIds}
                  preferredTileIds={preferredTileIds}
                  onOpenBookingDrawer={onOpenBookingDrawer}
                  onUnassignTile={onUnassignTile}
                  onOpenStaysSettings={onOpenStaysSettings}
                  onOpenFlightsSettings={onOpenFlightsSettings}
                  onRemoveBlock={onRemoveBlock}
                  isHighlighted={false}
                />
              </div>
            );
            return (
              <Fragment key={blockId}>
                {applyBlockWrapper(block, card.day_number, richBlockInner)}
              </Fragment>
            );
          }

          return (
            <TimelineBlockListLegacyBlock
              key={blockId}
              block={block}
              blockId={blockId}
              activeBlockId={activeBlockId}
              showPriceEstimates={showPriceEstimates}
            />
          );
        })
      )}

      {useRichBlocks && !isFreeDay && !isArrival && !isDeparture && !blocksToRender.every((block) => block.is_skeleton) && (
        <TimelineBlockListAddActivityButton
          dayNumber={card.day_number}
          date={card.date ?? null}
          disableFillDayActions={disableFillDayActions}
          onBrowse={onBrowse}
        />
      )}
    </div>
  );

  return isFreeDay ? blocksContainer : applyDayWrapper(card.day_number, blocksContainer);
}
