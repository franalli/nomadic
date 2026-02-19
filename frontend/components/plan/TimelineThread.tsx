'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */

import type { LucideIcon } from 'lucide-react';
import {
  AlertTriangle,
  Bed,
  Camera,
  Leaf,
  MapPin,
  Mountain,
  PlaneLanding,
  PlaneTakeoff,
  ShieldAlert,
  Sparkles,
  Sun,
  Utensils,
  Waves,
  Zap,
} from 'lucide-react';
import React, { type ReactNode } from 'react';
import { useMemo } from 'react';

import { getDayIntensity, INTENSITY_CONFIG } from '@/lib/dayIntensity';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { getTopicLabel } from './stages/StrategyHeroUtils';
import { FreeDayCard } from './timeline/blocks/FreeDayCard';
import { SafetyBlock } from './timeline/blocks/SafetyBlock';
import { InlineDatePrompt } from './timeline/InlineDatePrompt';
import { RichBlockRenderer } from './timeline/RichBlockRenderer';
import { useTimelineFillDay } from './timeline/useTimelineFillDay';

// =============================================================================
// Category Icons (mirrors ActivitiesSheet.ALL_CATEGORIES for inline picker)
// =============================================================================

const CATEGORY_ICONS: Record<string, string> = {
  diving: '\u{1F93F}', hiking: '\u{1F97E}', skiing: '\u26F7\uFE0F', cycling: '\u{1F6B4}',
  sailing: '\u26F5', surfing: '\u{1F3C4}', cooking: '\u{1F373}', yoga: '\u{1F9D8}',
  temples: '\u26E9\uFE0F', nightlife: '\u{1F389}', beach: '\u{1F3D6}\uFE0F', shopping: '\u{1F6CD}\uFE0F',
  photography: '\u{1F4F8}',
};

/**
 * Source specialist → categories excluded when a buffer block from that specialist
 * is present on the same day. Must mirror specialist_registry.py CrossDomainBlock
 * target_specialists exactly (currently: diving → skiing/hiking/climbing).
 */
const BUFFER_EXCLUSIONS: Record<string, string[]> = {
  diving: ['hiking', 'skiing', 'climbing'],
};

const INTENSITY_ICON_MAP: Record<string, LucideIcon> = { Leaf, Sun, Zap };

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
  /** Callback to open booking drawer for a category (optional dayNumber for pinned placement) */
  onOpenBookingDrawer?: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
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
  /** Callback to open stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
  /** Callback to open flights settings sheet */
  onOpenFlightsSettings?: () => void;
  /** Disable fill-day actions while streaming/regenerating */
  disableFillDayActions?: boolean;
  /** Callback to remove a block from the itinerary */
  onRemoveBlock?: (blockId: string, dayNumber: number) => void;
  /**
   * Optional wrapper applied to each block node.
   * Use this to inject DnD draggable/droppable wrappers without coupling TimelineThread to DnD.
   */
  blockWrapper?: (block: DayBlock, dayNumber: number, children: ReactNode) => ReactNode;
  /**
   * Optional wrapper applied to the entire block-list container for each day card.
   * Use this to inject a DroppableDay zone that covers the full day — including
   * free/empty days where blockWrapper never fires.
   *
   * Note: for free days, prefer `freeDayDropSlot` instead — it renders a dedicated
   * slot inside FreeDayCard without wrapping the entire card.
   */
  dayWrapper?: (dayNumber: number, children: ReactNode) => ReactNode;
  /**
   * Optional render prop for a drop zone slot inside FreeDayCard.
   * Called for days that render FreeDayCard (empty/free days only).
   * This slot appears between the subtitle and specialist chips inside the card,
   * avoiding the highlight-the-entire-card problem that dayWrapper causes on free days.
   */
  freeDayDropSlot?: (dayNumber: number) => ReactNode;
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
  onOpenStaysSettings,
  onOpenFlightsSettings,
  disableFillDayActions = false,
  onRemoveBlock,
  blockWrapper,
  dayWrapper,
  freeDayDropSlot,
}: TimelineThreadProps) {
  // Default identity wrapper — no-op when blockWrapper is not provided
  const applyBlockWrapper = blockWrapper ?? ((_b: DayBlock, _d: number, children: ReactNode) => children);
  // Default identity wrapper — no-op when dayWrapper is not provided
  const applyDayWrapper = dayWrapper ?? ((_d: number, children: ReactNode) => children);
  // Compute effective variant: prefer explicit variant, fall back to isDraft for backward compatibility
  const effectiveVariant: TimelineVariant = variant ?? (isDraft ? 'draft' : 'real');
  const { badge, badgeClass } = variantConfig[effectiveVariant];

  // Fill-day: delegated to extracted hook
  const tripInputs = useDocumentTripInputs();
  const destination = tripInputs?.destination ?? null;
  const categories = tripInputs?.activity_settings?.categories;
  const { fillingDay, fillDayRejection, handleFillDay } = useTimelineFillDay({
    disableFillDayActions,
    categories,
  });

  const sortedDays = useMemo(() => {
    return [...dayCards].sort((a, b) => a.day_number - b.day_number);
  }, [dayCards]);

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
              onMouseEnter={() => !document.body.hasAttribute('data-dnd-active') && onDayHover?.(card.day_number)}
              onMouseLeave={() => !document.body.hasAttribute('data-dnd-active') && onDayHover?.(null)}
              className="flex items-center gap-4 mb-4 w-full text-left group"
            >
              {/* Icon node on thread */}
              <div
                className={cn(
                  'timeline-node flex-shrink-0 w-9 h-9 rounded-full border flex items-center justify-center transition-colors',
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
                  {card.date && (
                    <span className="text-sm font-normal text-muted-foreground ml-2">
                      · {new Date(card.date + 'T00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                    </span>
                  )}
                  {(() => {
                    const intensity = getDayIntensity(card.blocks);
                    if (!intensity) return null;
                    const cfg = INTENSITY_CONFIG[intensity];
                    const Icon = INTENSITY_ICON_MAP[cfg.icon];
                    return (
                      <span className={cn(`ml-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${DS.textSize.mini} font-medium`, cfg.pillClass)}>
                        <Icon className="h-3 w-3" />
                        {cfg.label}
                      </span>
                    );
                  })()}
                </h3>
                {card.label && !/^Day \d+$/i.test(card.label) && (
                  <p className="text-sm text-muted-foreground truncate">{card.label}</p>
                )}
                {card.subtitle && (
                  <p className="text-xs text-muted-foreground/60 truncate">{card.subtitle}</p>
                )}
              </div>
            </button>

            {/* Blocks list — wrapped by dayWrapper (e.g. DroppableDay) when provided */}
            {(() => {
              // Filter blocks for rich rendering
              const blocksToRender = useRichBlocks ? filterBlocks(card.blocks) : card.blocks;

              // Separate buffer blocks (safety constraints) from content blocks
              // Exclude arrival/departure anchors from the SafetyBlock rendering path —
              // those are logistics blocks handled by LogisticsBlock, not SafetyBlock.
              const bufferBlocks = blocksToRender.filter(
                b => b.is_buffer && b.buffer_type !== 'arrival' && b.buffer_type !== 'departure'
              );
              const contentBlocks = blocksToRender.filter(b => !b.is_buffer);

              // Empty day or only free_day placeholder → interactive FreeDayCard
              // Buffer blocks render as SafetyBlock above the FreeDayCard
              // Never show FreeDayCard on arrival or departure days
              const isArrival = card.blocks.some(b => b.buffer_type === 'arrival');
              const isDeparture = card.blocks.some(b => b.buffer_type === 'departure');
              const hasOnlyFreeDay = contentBlocks.length === 1
                && contentBlocks[0].activity_type === 'free_day';
              // Buffer days (rest_day, no_fly, acclimatization) ARE fillable —
              // the constraint restricts which categories, not whether you can plan.
              // SafetyBlock renders as an informational banner; FreeDayCard provides the CTA.
              const isFreeDay = useRichBlocks && !isArrival && !isDeparture && (contentBlocks.length === 0 || hasOnlyFreeDay);

              // For free days: skip dayWrapper (it would highlight the entire FreeDayCard).
              // The drop zone is injected via freeDayDropSlot inside FreeDayCard instead.
              // For activity days: apply dayWrapper (DroppableDay) around the blocks list.
              const blocksContainer = (
              <div className="space-y-3 pl-[52px]">
                {(() => {
                if (isFreeDay) {
                  return (
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
                        availableCategories={(() => {
                          if (!categories || categories.length <= 1) return undefined;
                          // Derive categories excluded by buffer blocks on this day.
                          // A rest_day buffer from diving excludes hiking/climbing/skiing.
                          const excludedByBuffer = new Set<string>();
                          for (const buf of bufferBlocks) {
                            const st = (buf.specialist_type || '').toLowerCase();
                            if (st && BUFFER_EXCLUSIONS[st]) {
                              BUFFER_EXCLUSIONS[st].forEach(cat => excludedByBuffer.add(cat));
                            }
                          }
                          return categories
                            .filter(c => !excludedByBuffer.has(c.toLowerCase()))
                            .map(c => ({
                              value: c,
                              label: c.charAt(0).toUpperCase() + c.slice(1),
                              icon: CATEGORY_ICONS[c.toLowerCase()] ?? '\u{1F3AF}',
                            }));
                        })()}
                        onBrowse={() => onOpenBookingDrawer?.('activity', card.day_number)}
                        onFillDay={handleFillDay}
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
                  );
                }

                return blocksToRender.map((block, _filteredIndex) => {
                  // Find original index in card.blocks for consistent ID generation
                  // (needed because filterBlocks may reindex the array)
                  const originalIndex = card.blocks.indexOf(block);
                  const blockIndex = originalIndex !== -1 ? originalIndex : _filteredIndex;

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
                    const richBlockInner = (
                      <div
                        id={`timeline-item-${blockId}`}
                        data-map-id={blockId}
                        className={cn(
                          'transition-all duration-300',
                          isActiveBlock && 'ring-2 ring-emerald-500 ring-offset-2 ring-offset-background rounded-xl scale-[1.01]'
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
                      id={`timeline-item-${blockId}`}
                      data-map-id={blockId}
                      className={cn(
                        'rounded-xl border p-4 transition-all relative',
                        isUnschedulable
                          ? 'bg-zinc-100/50 dark:bg-zinc-900/30 border-dashed border-amber-500/50 opacity-60'
                          : isBlockSafety
                            ? 'bg-zinc-500/5 border-zinc-500/20'
                            : isActiveBlock
                              ? 'scale-[1.02] border-emerald-500/50 shadow-soft bg-card'
                              : 'bg-card border-border hover:border-primary/50 hover:shadow-soft'
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
                              ? 'bg-amber-500/10 text-amber-500'
                              : isBlockSafety
                                ? 'bg-zinc-500/10 text-zinc-500'
                                : 'bg-muted text-muted-foreground'
                          )}
                        >
                          {isUnschedulable ? <AlertTriangle className="w-4 h-4" /> : <BlockIcon className="w-4 h-4" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                'text-xs font-medium uppercase tracking-wide',
                                isUnschedulable ? 'text-amber-500' : isBlockSafety ? 'text-zinc-500' : 'text-muted-foreground'
                              )}
                            >
                              {block.period}
                            </span>
                            {/* Intensity badge - hide for free/rest/buffer days */}
                            {block.intensity && !block.is_buffer && (() => {
                              const activityLower = (block.activity_type || '').toLowerCase();
                              const summaryLower = (block.summary || '').toLowerCase();
                              const isFreeDay = ['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
                                keyword => activityLower.includes(keyword) || summaryLower.includes(keyword)
                              );
                              if (isFreeDay) return null;
                              return (
                                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                                  {block.intensity}
                                </span>
                              );
                            })()}
                            {/* Specialist type badge for ghost timeline blocks */}
                            {block.specialist_type && (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">
                                {getTopicLabel(block.specialist_type)}
                              </span>
                            )}
                          </div>
                          <p
                            className={cn(
                              'mt-1 font-medium',
                              isUnschedulable
                                ? 'line-through text-zinc-500'
                                : isBlockSafety
                                  ? 'text-zinc-600 dark:text-zinc-400'
                                  : 'text-foreground'
                            )}
                          >
                            {block.activity_type || block.summary}
                          </p>
                          <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
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
              );

              return isFreeDay ? blocksContainer : applyDayWrapper(card.day_number, blocksContainer);
            })()}
          </div>
        );
      })}
    </div>
  );
}

export default TimelineThread;
