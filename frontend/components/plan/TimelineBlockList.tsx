'use client';

/**
 * TimelineBlockList
 *
 * Renders the block list for a single day card in the timeline.
 * Handles free day rendering (buffer constraints + FreeDayCard),
 * skeleton blocks (ghost timeline), rich blocks (S3), and legacy blocks.
 *
 * Extracted from TimelineThread to reduce file size.
 */

import type { LucideIcon } from 'lucide-react';
import {
  AlertTriangle,
  Bed,
  Camera,
  Mountain,
  PlaneLanding,
  PlaneTakeoff,
  ShieldAlert,
  Sparkles,
  Utensils,
  Waves,
} from 'lucide-react';
import React, { type ReactNode } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useUIStore } from '@/state/uiStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { getTopicLabel } from './stages/StrategyHeroUtils';
import { FreeDayCard } from './timeline/blocks/FreeDayCard';
import { SafetyBlock } from './timeline/blocks/SafetyBlock';
import { RichBlockRenderer } from './timeline/RichBlockRenderer';
import { computeBufferExclusions } from './useTimelineBufferLogic';

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Get icon for a block based on its type and content.
 */
function getIconForBlock(block: DayBlock): LucideIcon {
  const type = block.activity_type?.toLowerCase() || '';
  const summary = block.summary?.toLowerCase() || '';

  // Buffer types first
  if (block.buffer_type === 'arrival') return PlaneLanding;
  if (block.buffer_type === 'departure') return PlaneTakeoff;
  if (block.is_buffer || block.buffer_type) return ShieldAlert;

  // Activity type detection
  if (type.includes('dive') || summary.includes('dive') || summary.includes('snorkel')) return Waves;
  if (type.includes('hike') || summary.includes('hike') || summary.includes('trek')) return Mountain;
  if (type.includes('meal') || type.includes('dining') || summary.includes('dinner') || summary.includes('lunch')) return Utensils;
  if (type.includes('hotel') || type.includes('stay') || summary.includes('check-in') || summary.includes('check in')) return Bed;
  if (type.includes('tour') || summary.includes('tour') || summary.includes('sightseeing')) return Camera;

  return Sparkles; // Default activity icon
}

/**
 * Filter blocks to remove generic "Explore X" when specialist content exists.
 * This prevents duplicate/redundant suggestions.
 */
function filterBlocks(blocks: DayBlock[]): DayBlock[] {
  // Check if specialist content exists (excluding general/local_expert)
  const hasSpecialist = blocks.some(
    (b) => b.specialist_type && !['general', 'local_expert'].includes(b.specialist_type)
  );

  if (!hasSpecialist) return blocks;

  return blocks.filter((block) => {
    const summary = (block.summary || '').toLowerCase();
    const type = (block.activity_type || '').toLowerCase();

    // Keep specialist blocks
    if (block.specialist_type && !['general', 'local_expert'].includes(block.specialist_type)) {
      return true;
    }

    // Filter generic explore suggestions when specialist content exists
    if (summary.includes('explore') || type.includes('general')) {
      return false;
    }

    return true;
  });
}

// =============================================================================
// Props
// =============================================================================

export interface TimelineBlockListProps {
  card: DayCard;
  dayCards: DayCard[];
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
  // Free day props
  destination: string | null;
  categories: string[] | undefined;
  fillingDay: number | null;
  fillDayRejection: { dayNumber: number; reason: string } | null;
  handleFillDay: (dayNumber: number, dayDate: string | null, categories?: string[]) => Promise<void>;
  disableFillDayActions: boolean;
  onBrowse: (dayNumber: number, date: string | null) => void;
}

// =============================================================================
// Component
// =============================================================================

export function TimelineBlockList({
  card,
  dayCards,
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
  // Default identity wrappers — no-op when not provided
  const applyBlockWrapper = blockWrapper ?? ((_b: DayBlock, _d: number, children: ReactNode) => children);
  const applyDayWrapper = dayWrapper ?? ((_d: number, children: ReactNode) => children);

  // Filter blocks for rich rendering
  const blocksToRender = useRichBlocks ? filterBlocks(card.blocks) : card.blocks;

  // Separate buffer blocks (safety constraints) from content blocks
  // Exclude arrival/departure anchors from the SafetyBlock rendering path --
  // those are logistics blocks handled by LogisticsBlock, not SafetyBlock.
  const bufferBlocks = blocksToRender.filter(
    b => b.is_buffer && b.buffer_type !== 'arrival' && b.buffer_type !== 'departure'
  );
  const contentBlocks = blocksToRender.filter(b => !b.is_buffer);

  // Empty day or only free_day placeholder -> interactive FreeDayCard
  // Buffer blocks render as SafetyBlock above the FreeDayCard
  // Never show FreeDayCard on arrival or departure days
  const isArrival = card.blocks.some(b => b.buffer_type === 'arrival');
  const isDeparture = card.blocks.some(b => b.buffer_type === 'departure');
  const hasOnlyFreeDay = contentBlocks.length === 1
    && contentBlocks[0].activity_type === 'free_day';
  // Buffer days (rest_day, no_fly, acclimatization) ARE fillable --
  // the constraint restricts which categories, not whether you can plan.
  // SafetyBlock renders as an informational banner; FreeDayCard provides the CTA.
  const isFreeDay = useRichBlocks && !isArrival && !isDeparture && (contentBlocks.length === 0 || hasOnlyFreeDay);

  // Compute buffer exclusion logic for free day chips
  const { chipsToShow, isConstraintBuffer } = computeBufferExclusions(
    bufferBlocks, dayCards, card.day_number, categories,
  );

  // For free days: skip dayWrapper (it would highlight the entire FreeDayCard).
  // The drop zone is injected via freeDayDropSlot inside FreeDayCard instead.
  // For activity days: apply dayWrapper (DroppableDay) around the blocks list.
  const blocksContainer = (
    <div className="space-y-4 pl-[52px]">
      {isFreeDay ? (
        <>
          {bufferBlocks.map((block, i) => {
            const bufId = `${card.day_number}-buf-${i}`;
            return (
              <SafetyBlock
                key={bufId}
                reason={block.buffer_reason || (block.buffer_type === 'no_fly' ? '24h no-fly buffer before flight' : 'Rest day recommended')}
                until={block.buffer_type === 'no_fly' ? block.scheduled_time : undefined}
                type={block.buffer_type as 'no_fly' | 'rest_day' | 'acclimatization' | undefined}
              />
            );
          })}
          <FreeDayCard
            dayNumber={card.day_number}
            dayDate={card.date ?? null}
            destination={destination}
            availableCategories={chipsToShow}
            isConstraintBuffer={isConstraintBuffer}
            onBrowse={() => onBrowse(card.day_number, card.date ?? null)}
            onFillDay={isConstraintBuffer ? undefined : handleFillDay}
            isFilling={fillingDay === card.day_number}
            isDisabled={disableFillDayActions}
            rejectionMessage={
              fillDayRejection?.dayNumber === card.day_number
                ? fillDayRejection.reason
                : undefined
            }
            dropZoneSlot={freeDayDropSlot?.(card.day_number)}
          />
        </>
      ) : (
        blocksToRender.map((block, _filteredIndex) => {
          // Find original index in card.blocks for consistent ID generation
          // (needed because filterBlocks may reindex the array)
          const originalIndex = card.blocks.indexOf(block);
          const blockIndex = originalIndex !== -1 ? originalIndex : _filteredIndex;

          // Skeleton block rendering for ghost timeline
          if (block.is_skeleton) {
            return (
              <div
                key={blockIndex}
                className="rounded-xl border border-dashed border-zinc-200/50 dark:border-white/10 bg-zinc-100/10 dark:bg-white/[0.03] p-4 opacity-60"
              >
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 w-8 h-8 rounded-full bg-zinc-200 dark:bg-zinc-700 animate-pulse" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-24 bg-zinc-200 dark:bg-zinc-700 rounded animate-pulse" />
                    <div className="h-3 w-48 bg-zinc-200/60 dark:bg-zinc-700/60 rounded animate-pulse" />
                  </div>
                </div>
                <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400 text-center">
                  Planning Day {card.day_number}...
                </p>
              </div>
            );
          }

          // Use block.id if available, otherwise generate from day/index
          const blockId = block.id || `block-${card.day_number}-${blockIndex}`;

          // === RICH BLOCK RENDERING (S3 Itinerary View) ===
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
                  isActiveBlock && 'ring-2 ring-emerald-500 ring-offset-2 ring-offset-background rounded-xl scale-[1.01]',
                  '[&[data-map-hovered=true]]:ring-1 [&[data-map-hovered=true]]:ring-blue-400/60 [&[data-map-hovered=true]]:rounded-xl',
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
              <React.Fragment key={blockId}>
                {applyBlockWrapper(block, card.day_number, richBlockInner)}
              </React.Fragment>
            );
          }

          // === LEGACY BLOCK RENDERING ===
          // Note: applyBlockWrapper is intentionally not called here.
          // blockWrapper only applies when useRichBlocks={true}.
          const BlockIcon = getIconForBlock(block);
          const isBlockSafety = block.is_buffer || !!block.buffer_type;
          const isActiveBlock = activeBlockId === blockId;
          const isUnschedulable = block.unschedulable === true;

          return (
            <div
              key={blockIndex}
              onMouseEnter={() => useUIStore.getState().setHoveredActivityId(blockId)}
              onMouseLeave={() => useUIStore.getState().setHoveredActivityId(null)}
              id={`timeline-item-${blockId}`}
              data-map-id={blockId}
              className={cn(
                'rounded-xl border p-4 transition-all relative',
                isUnschedulable
                  ? 'bg-zinc-100/50 dark:bg-zinc-900/30 border-dashed border-amber-500/50 opacity-60'
                  : isBlockSafety
                    ? 'bg-zinc-500/5 border-zinc-500/20'
                    : isActiveBlock
                      ? 'scale-[1.02] border-emerald-500/50 shadow-soft bg-white dark:bg-zinc-900'
                      : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-white/10 hover:border-emerald-500/50 hover:shadow-soft'
              )}
            >
              {/* Unschedulable warning banner */}
              {isUnschedulable && (
                <div className="absolute -top-2 left-3 flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/30">
                  <AlertTriangle className="w-3 h-3 text-amber-500" />
                  <span className={`${DS.textSize.micro} font-semibold text-amber-600 dark:text-amber-400`}>Cannot schedule</span>
                </div>
              )}

              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
                    isUnschedulable
                      ? 'bg-amber-500/10 dark:bg-amber-500/15 text-amber-600 dark:text-amber-300'
                      : isBlockSafety
                        ? 'bg-zinc-500/10 dark:bg-zinc-500/15 text-zinc-600 dark:text-zinc-400'
                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400'
                  )}
                >
                  {isUnschedulable ? <AlertTriangle className="w-4 h-4" /> : <BlockIcon className="w-4 h-4" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'text-xs font-medium uppercase tracking-wide',
                        isUnschedulable
                          ? 'text-amber-600 dark:text-amber-300'
                          : isBlockSafety
                            ? 'text-zinc-600 dark:text-zinc-400'
                            : 'text-zinc-500 dark:text-zinc-400'
                      )}
                    >
                      {block.period}
                    </span>
                    {/* Intensity badge - hide for free/rest/buffer days */}
                    {block.intensity && !block.is_buffer && (() => {
                      const activityLower = (block.activity_type || '').toLowerCase();
                      const summaryLower = (block.summary || '').toLowerCase();
                      const isFreeDayBlock = ['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
                        keyword => activityLower.includes(keyword) || summaryLower.includes(keyword)
                      );
                      if (isFreeDayBlock) return null;
                      return (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400">
                          {block.intensity}
                        </span>
                      );
                    })()}
                    {/* Specialist type badge for ghost timeline blocks */}
                    {block.specialist_type && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-medium">
                        {getTopicLabel(block.specialist_type)}
                      </span>
                    )}
                  </div>
                  <p
                    className={cn(
                      'mt-1 font-medium',
                      isUnschedulable
                        ? 'line-through text-zinc-500 dark:text-zinc-400'
                        : isBlockSafety
                          ? 'text-zinc-600 dark:text-zinc-400'
                          : 'text-zinc-900 dark:text-white'
                    )}
                  >
                    {block.activity_type || block.summary}
                  </p>
                  <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                    {block.summary}
                  </p>

                  {/* Unschedulable reason */}
                  {isUnschedulable && block.unschedulable_reason && (
                    <p className="mt-1.5 text-xs text-amber-600/80 dark:text-amber-400/70 italic">
                      {block.unschedulable_reason}
                    </p>
                  )}

                  {/* Specialist constraint pills */}
                  {block.constraints && block.constraints.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {block.constraints.map((constraint, i) => (
                        <span
                          key={i}
                          className="text-xs px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 font-medium"
                        >
                          {constraint}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Price estimate - Plan mode only */}
                  {showPriceEstimates && block.price_estimate && (
                    <span className="mt-2 inline-block text-xs text-zinc-500 dark:text-zinc-400 font-medium">
                      ~${block.price_estimate.toLocaleString()}
                    </span>
                  )}

                  {/* Buffer reason */}
                  {block.buffer_reason && (
                    <div className="mt-2 text-xs font-medium px-2 py-1 rounded bg-zinc-500/10 dark:bg-zinc-500/15 inline-block text-zinc-600 dark:text-zinc-400">
                      {block.buffer_reason}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })
      )}
      {/* Add activity button — rich activity days only (not free/arrival/departure/skeleton) */}
      {useRichBlocks && !isFreeDay && !isArrival && !isDeparture
        && !blocksToRender.every(b => b.is_skeleton) && (
        <button
          type="button"
          onClick={() => onBrowse(card.day_number, card.date ?? null)}
          className={cn(
            "w-full py-3 rounded-xl text-sm font-medium border-2 border-dashed transition-all duration-200",
            "border-white/10 text-zinc-500",
            "hover:border-emerald-500/30 hover:text-emerald-400",
            "hover:shadow-[0_0_15px_-5px_rgba(16,185,129,0.15)]",
            "active:scale-[0.98]",
            disableFillDayActions
              ? 'cursor-not-allowed pointer-events-none'
              : ''
          )}
        >
          + Add activity
        </button>
      )}
    </div>
  );

  return isFreeDay ? blocksContainer : applyDayWrapper(card.day_number, blocksContainer);
}
