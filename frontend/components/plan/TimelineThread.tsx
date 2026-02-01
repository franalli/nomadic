'use client';

import type { LucideIcon } from 'lucide-react';
import {
  Bed,
  Camera,
  MapPin,
  Mountain,
  PlaneLanding,
  PlaneTakeoff,
  ShieldAlert,
  Sparkles,
  Utensils,
  Waves,
} from 'lucide-react';
import { useCallback, useMemo } from 'react';

import { cn } from '@/lib/utils';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { InlineDatePrompt } from './timeline/InlineDatePrompt';
import {
  ActivityMiniCard,
  FreeDayCard,
  GhostSlot,
  LogisticsBlock,
  SafetyBlock,
  getDisplayTime,
} from './timeline/blocks';

// =============================================================================
// Timeline Variant System (Grand Unification)
// =============================================================================

/**
 * Timeline rendering mode - determines badge and styling.
 * @see docs/ux_unified_architecture.md
 */
export type TimelineVariant = 'ghost' | 'draft' | 'real';

/**
 * Configuration for each timeline variant.
 */
const variantConfig: Record<TimelineVariant, { badge: string | null; badgeClass: string }> = {
  ghost: {
    badge: 'Specialist Preview',
    badgeClass: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  draft: {
    badge: 'Draft Itinerary',
    badgeClass: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  real: {
    badge: null,
    badgeClass: '',
  },
};

interface TimelineThreadProps {
  dayCards: DayCard[];
  /** Currently expanded day (for accordion behavior) */
  expandedDay?: number | null;
  /** Callback when a day is clicked */
  onDayClick?: (dayNumber: number) => void;
  /** Show price estimates in Plan mode (~$150) */
  showPriceEstimates?: boolean;
  /** Active block ID for scroll spy highlight (map integration) */
  activeBlockId?: string | null;
  /**
   * @deprecated Use `variant` instead for clearer semantics
   * Draft mode - shows "Draft Preview" badge for ghost timeline
   */
  isDraft?: boolean;
  /**
   * Timeline rendering mode (Grand Unification)
   * - ghost: Speculative pre-plan timeline (Specialist Preview badge)
   * - draft: Generated but unfinalized (Draft Itinerary badge)
   * - real: Confirmed itinerary (no badge)
   */
  variant?: TimelineVariant;
  // Inline date prompt props (Change 2)
  /** Whether trip has duration set (end_date OR trip_duration) */
  hasDuration?: boolean;
  /** Start date in ISO format for InlineDatePrompt */
  startDate?: string | null;
  /** Called when user selects a quick pick nights option */
  onSelectNights?: (nights: number) => void;
  /** Called when user wants to open the full date picker */
  onOpenDatePicker?: () => void;
  // === NEW: S3 Itinerary View props ===
  /** Callback when hovering a day (for map sync) */
  onDayHover?: (dayNumber: number | null) => void;
  /** Callback to open booking drawer for a category */
  onOpenBookingDrawer?: (category: 'hotel' | 'flight' | 'activity') => void;
  /** Callback to unassign a booked tile from a block */
  onUnassignTile?: (blockId: string) => void;
  /** Set of saved tile IDs for booking state */
  savedTileIds?: Set<string>;
  /** Use rich block rendering (S3 Itinerary View) */
  useRichBlocks?: boolean;
  // === Unified Planning View props ===
  /** Current view mode (planning vs booking) - controls Book button visibility */
  mode?: 'planning' | 'booking';
  /** Set of preferred tile IDs for attribution badges */
  preferredTileIds?: Set<string>;
}

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
 * Get the primary icon for a day based on its blocks.
 */
function getDayIcon(card: DayCard, isFirst: boolean, isLast: boolean): LucideIcon {
  // Arrival day
  if (isFirst || card.blocks.some((b) => b.buffer_type === 'arrival')) return PlaneLanding;
  // Departure day
  if (isLast || card.blocks.some((b) => b.buffer_type === 'departure')) return PlaneTakeoff;
  // Safety buffer day
  if (card.blocks.some((b) => ['no_fly', 'acclimatization', 'rest_day'].includes(b.buffer_type || ''))) return ShieldAlert;
  // Otherwise, use the first block's icon
  if (card.blocks.length > 0) return getIconForBlock(card.blocks[0]);
  return MapPin;
}

/**
 * Check if a day is a safety buffer day.
 */
function isSafetyDay(card: DayCard): boolean {
  return card.blocks.some((b) => ['no_fly', 'acclimatization', 'rest_day'].includes(b.buffer_type || ''));
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

/**
 * TimelineThread
 *
 * Renders day cards in a "beads on a string" timeline layout.
 * Features:
 * - Vertical connecting line on the left
 * - Smart icons for each day type
 * - Safety buffer styling for constraint days
 * - Rich block rendering (S3 Itinerary View)
 */
export function TimelineThread({
  dayCards,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  expandedDay: _expandedDay,
  onDayClick,
  showPriceEstimates = false,
  activeBlockId,
  isDraft = false,
  variant,
  hasDuration = true,
  startDate,
  onSelectNights,
  onOpenDatePicker,
  // S3 Itinerary View props
  onDayHover,
  onOpenBookingDrawer,
  onUnassignTile,
  savedTileIds,
  useRichBlocks = false,
  // Unified Planning View props
  mode = 'planning',
  preferredTileIds,
}: TimelineThreadProps) {
  // Compute effective variant: prefer explicit variant, fall back to isDraft for backward compatibility
  const effectiveVariant: TimelineVariant = variant ?? (isDraft ? 'draft' : 'real');
  const { badge, badgeClass } = variantConfig[effectiveVariant];
  const sortedDays = useMemo(() => {
    return [...dayCards].sort((a, b) => a.day_number - b.day_number);
  }, [dayCards]);

  /**
   * Smart block renderer for S3 Itinerary View.
   * Routes to appropriate component based on block type and state.
   */
  const renderRichBlock = useCallback(
    (block: DayBlock, blockIndex: number, blockId: string) => {
      // 1. LOGISTICS LAYER - Hard times (arrival/departure/check-in/check-out)
      if (block.buffer_type === 'arrival' || block.buffer_type === 'departure') {
        return (
          <LogisticsBlock
            key={blockId}
            type={block.buffer_type}
            time={getDisplayTime(block, blockIndex)}
            details={block.logistics_details}
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
            hotelName={block.hotel_name}
            details={block.logistics_details}
            // Preference attribution for hotels
            preferenceStatus={block.preference_status}
            alternativeTileId={block.alternative_tile_id}
          />
        );
      }
      if (activityLower.includes('check-out') || activityLower.includes('check out')) {
        return (
          <LogisticsBlock
            key={blockId}
            type="checkout"
            time={getDisplayTime(block, blockIndex)}
            hotelName={block.hotel_name}
            details={block.logistics_details}
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
      const isBooked = !!block.booked_tile || !!(block.id && savedTileIds?.has(block.id));

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
        />
      );
    },
    [onOpenBookingDrawer, onUnassignTile, savedTileIds, mode, preferredTileIds]
  );

  if (sortedDays.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground border-2 border-dashed rounded-xl">
        Generating your itinerary...
      </div>
    );
  }

  return (
    <div className="relative pl-4 pr-2 py-6 space-y-8 timeline-thread">
      {/* Variant badge for non-real timelines */}
      {badge && (
        <div className="absolute top-2 right-2 z-10">
          <span className={cn(
            'text-xs px-2 py-1 rounded-full border border-border/50 font-medium',
            badgeClass
          )}>
            {badge}
          </span>
        </div>
      )}

      {/* Inline date prompt when duration is missing */}
      {!hasDuration && onSelectNights && onOpenDatePicker && (
        <InlineDatePrompt
          startDate={startDate ?? null}
          onSelectNights={onSelectNights}
          onOpenDatePicker={onOpenDatePicker}
        />
      )}

      {sortedDays.map((card, index) => {
        const isFirst = index === 0;
        const isLast = index === sortedDays.length - 1;
        const DayIcon = getDayIcon(card, isFirst, isLast);
        const isSafety = isSafetyDay(card);

        return (
          <div key={card.day_number} className="relative z-10">
            {/* Day header with icon */}
            <button
              type="button"
              onClick={() => onDayClick?.(card.day_number)}
              onMouseEnter={() => onDayHover?.(card.day_number)}
              onMouseLeave={() => onDayHover?.(null)}
              className="flex items-center gap-4 mb-4 w-full text-left group"
            >
              {/* Icon node on thread */}
              <div
                className={cn(
                  'timeline-node flex-shrink-0 w-9 h-9 rounded-full border flex items-center justify-center transition-colors shadow-sm',
                  isSafety
                    ? 'bg-zinc-500/10 border-zinc-500/50 text-zinc-500'
                    : 'bg-background border-muted-foreground/30 text-muted-foreground group-hover:border-primary group-hover:text-primary'
                )}
              >
                <DayIcon className="w-4 h-4" />
              </div>

              {/* Day title */}
              <div className="flex-1 min-w-0">
                <h3
                  className={cn(
                    'text-lg font-semibold tracking-tight',
                    isSafety ? 'text-zinc-500' : 'text-foreground'
                  )}
                >
                  Day {card.day_number}
                </h3>
                <p className="text-sm text-muted-foreground truncate">{card.label}</p>
              </div>
            </button>

            {/* Blocks list */}
            <div className="space-y-3 pl-[52px]">
              {(() => {
                // Filter blocks for rich rendering
                const blocksToRender = useRichBlocks ? filterBlocks(card.blocks) : card.blocks;

                // Empty day state (only for rich blocks)
                if (useRichBlocks && blocksToRender.length === 0) {
                  return (
                    <FreeDayCard
                      dayNumber={card.day_number}
                      onBrowse={() => onOpenBookingDrawer?.('activity')}
                    />
                  );
                }

                return blocksToRender.map((block, blockIndex) => {
                  // Skeleton block rendering for ghost timeline
                  if (block.is_skeleton) {
                    return (
                      <div
                        key={blockIndex}
                        className="rounded-xl border border-dashed border-border/50 bg-muted/10 p-4 opacity-60"
                      >
                        <div className="flex items-start gap-3">
                          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-muted animate-pulse" />
                          <div className="flex-1 space-y-2">
                            <div className="h-4 w-24 bg-muted rounded animate-pulse" />
                            <div className="h-3 w-48 bg-muted/60 rounded animate-pulse" />
                          </div>
                        </div>
                        <p className="mt-3 text-xs text-muted-foreground text-center">
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
                    return (
                      <div
                        key={blockId}
                        id={`timeline-item-${blockId}`}
                        data-map-id={blockId}
                        className={cn(
                          'transition-all duration-300',
                          isActiveBlock && 'ring-2 ring-emerald-500 ring-offset-2 ring-offset-background rounded-xl scale-[1.01]'
                        )}
                      >
                        {renderRichBlock(block, blockIndex, blockId)}
                      </div>
                    );
                  }

                  // === LEGACY BLOCK RENDERING ===
                  const BlockIcon = getIconForBlock(block);
                  const isBlockSafety = block.is_buffer || !!block.buffer_type;
                  const isActiveBlock = activeBlockId === blockId;

                  return (
                    <div
                      key={blockIndex}
                      id={`timeline-item-${blockId}`}
                      data-map-id={blockId}
                      className={cn(
                        'rounded-xl border p-4 transition-all',
                        isBlockSafety
                          ? 'bg-zinc-500/5 border-zinc-500/20'
                          : isActiveBlock
                            ? 'scale-[1.02] border-emerald-500/50 shadow-lg bg-card'
                            : 'bg-card border-border hover:border-primary/50 hover:shadow-md'
                      )}
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={cn(
                            'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
                            isBlockSafety
                              ? 'bg-zinc-500/10 text-zinc-500'
                              : 'bg-muted text-muted-foreground'
                          )}
                        >
                          <BlockIcon className="w-4 h-4" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                'text-xs font-medium uppercase tracking-wide',
                                isBlockSafety ? 'text-zinc-500' : 'text-muted-foreground'
                              )}
                            >
                              {block.period}
                            </span>
                            {block.intensity && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                                {block.intensity}
                              </span>
                            )}
                            {/* Specialist type badge for ghost timeline blocks */}
                            {block.specialist_type && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">
                                {block.specialist_type}
                              </span>
                            )}
                          </div>
                          <p
                            className={cn(
                              'mt-1 font-medium',
                              isBlockSafety ? 'text-zinc-600 dark:text-zinc-400' : 'text-foreground'
                            )}
                          >
                            {block.activity_type || block.summary}
                          </p>
                          <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
                            {block.summary}
                          </p>

                          {/* Specialist constraint pills */}
                          {block.constraints && block.constraints.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {block.constraints.map((constraint, i) => (
                                <span
                                  key={i}
                                  className="text-xs px-2 py-0.5 rounded-full bg-zinc-500/10 text-zinc-500 font-medium"
                                >
                                  💡 {constraint}
                                </span>
                              ))}
                            </div>
                          )}

                          {/* Price estimate - Plan mode only */}
                          {showPriceEstimates && block.price_estimate && (
                            <span className="mt-2 inline-block text-xs text-muted-foreground font-medium">
                              ~${block.price_estimate.toLocaleString()}
                            </span>
                          )}

                          {/* Buffer reason */}
                          {block.buffer_reason && (
                            <div className="mt-2 text-xs font-medium px-2 py-1 rounded bg-zinc-500/10 inline-block text-zinc-600 dark:text-zinc-400">
                              {block.buffer_reason}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default TimelineThread;
