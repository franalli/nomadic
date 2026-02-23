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
import React, { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useMapSync } from '@/hooks/useMapSync';
import { apiFetch } from '@/lib/api';
import { getDayIntensity, INTENSITY_CONFIG } from '@/lib/dayIntensity';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { useUIStore } from '@/state/uiStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { BrowseActivitiesSheet } from './BrowseActivitiesSheet';
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

/**
 * Adjacent-day cross-domain exclusions — mirrors specialist_registry.py CrossDomainBlock.
 * Key = specialist present on adjacent day → value = categories blocked on target day.
 * Covers both directions:
 *   - diving on N-1 blocks hiking/skiing/climbing on N (forward: altitude-after-dive)
 *   - hiking/skiing/climbing on N+1 blocks diving on N (reverse: dive-before-altitude)
 */
const ADJACENT_EXCLUSIONS: Record<string, string[]> = {
  diving: ['hiking', 'skiing', 'climbing'],
  hiking: ['diving'],
  skiing: ['diving'],
  climbing: ['diving'],
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

  // Bidirectional map↔card hover sync — DOM-based to avoid full-tree re-renders.
  // useUIStore.subscribe writes directly to DOM attributes; no React state involved.
  useEffect(() => {
    let prevId: string | null = null;
    const unsub = useUIStore.subscribe((state) => {
      const id = state.hoveredActivityId;
      if (id === prevId) return;
      if (prevId) {
        document.getElementById(`timeline-item-${prevId}`)?.removeAttribute('data-map-hovered');
      }
      if (id) {
        document.getElementById(`timeline-item-${id}`)?.setAttribute('data-map-hovered', 'true');
      }
      prevId = id;
    });
    return unsub;
  }, []);

  // Fill-day: delegated to extracted hook
  const { destination, categories } = useDocumentStore(
    useShallow((s) => ({
      destination: s.document?.trip_inputs?.destination ?? null,
      categories: s.document?.trip_inputs?.activity_settings?.categories,
    }))
  );
  const { fillingDay, fillDayRejection, handleFillDay } = useTimelineFillDay({
    disableFillDayActions,
    categories,
  });

  // Browse Activities sheet state
  const [browseSheetOpen, setBrowseSheetOpen] = useState(false);
  const [browseSheetDay, setBrowseSheetDay] = useState<{ dayNumber?: number; date?: string | null } | null>(null);
  const browseableActivities = useDocumentStore((s) => s.browseableActivities);

  const handleSelectActivity = useCallback(async (tile: import('@/lib/api').BrowseTile) => {
    const targetDay = browseSheetDay?.dayNumber;
    if (!targetDay) return;

    setBrowseSheetOpen(false);

    const { document: currentDoc } = useDocumentStore.getState();
    if (!currentDoc) return;

    try {
      const res = await apiFetch('/api/document/insert-activity-block', {
        method: 'POST',
        body: JSON.stringify({
          day_number: targetDay,
          tile,
        }),
      });
      if (!res.ok) return;
      const result = await res.json();
      // Optimistically update the store with the returned day_card
      const doc = useDocumentStore.getState().document;
      if (!doc) return;
      const dayCards = (doc.day_cards ?? []).map((dc) =>
        dc.day_number === targetDay ? result.day_card : dc
      );
      useDocumentStore.setState({ document: { ...doc, day_cards: dayCards }, version: result.version });
    } catch {
      // Silent fail — the itinerary wasn't modified
    }
  }, [browseSheetDay]);

  const sortedDays = useMemo(() => {
    return [...dayCards].sort((a, b) => a.day_number - b.day_number);
  }, [dayCards]);

  // ── Map sync: day header refs for IntersectionObserver ─────────────────
  // Only active for variant="real" — ghost/draft have no stable block IDs.
  const dayHeaderRefs = useRef<Map<number, HTMLElement>>(new Map());
  const scrollContainerRef = useRef<HTMLElement | null>(null);

  // Debounce helper: fire only after `ms` ms of quiet
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const debouncedSetDay = useCallback((day: number) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      useMapSync.getState().setVisibleDayNumber(day);
    }, 150);
  }, []);

  // IntersectionObserver: update visibleDayNumber when a day header scrolls into view
  useEffect(() => {
    if (effectiveVariant !== 'real') return;

    // Walk up DOM to find scroll container (first scrollable ancestor)
    let firstHeader: HTMLElement | undefined;
    for (const v of dayHeaderRefs.current.values()) { firstHeader = v; break; }
    if (firstHeader) {
      let el: HTMLElement | null = firstHeader.parentElement;
      while (el) {
        const overflow = window.getComputedStyle(el).overflowY;
        if (overflow === 'auto' || overflow === 'scroll') {
          scrollContainerRef.current = el;
          break;
        }
        el = el.parentElement;
      }
    }

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the most visible intersecting day header
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);

        if (visible.length > 0) {
          const dayNumber = parseInt(
            visible[0].target.getAttribute('data-day') ?? '0',
            10,
          );
          if (dayNumber > 0) {
            debouncedSetDay(dayNumber);
          }
        }
      },
      {
        root: scrollContainerRef.current ?? null,
        rootMargin: '-30% 0px -30% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1],
      },
    );

    dayHeaderRefs.current.forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [sortedDays, effectiveVariant, debouncedSetDay]);

  // ── Map sync: listen for pin-click scroll requests ─────────────────────
  const scrollTarget = useMapSync((s) => s.scrollTargetDayNumber);
  const clearScrollTarget = useMapSync((s) => s.clearScrollTarget);

  useEffect(() => {
    if (scrollTarget === null || effectiveVariant !== 'real') return;

    const dayEl = dayHeaderRefs.current.get(scrollTarget);
    if (dayEl) {
      dayEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    clearScrollTarget();
  }, [scrollTarget, effectiveVariant, clearScrollTarget]);

  if (sortedDays.length === 0) {
    return (
      <div className="text-center py-12 text-zinc-500 dark:text-zinc-400 border-2 border-dashed border-zinc-200 dark:border-white/10 rounded-xl">
        Generating your itinerary...
      </div>
    );
  }

  return (
    <>
    <div className="relative pl-4 pr-2 py-6 space-y-8 timeline-thread">
      {/* Variant badge for non-real timelines */}
      {badge && (
        <div className="absolute top-2 right-2 z-10">
          <span className={cn(
            'text-xs px-2 py-1 rounded-full border border-zinc-200/50 dark:border-white/10 font-medium',
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
          <div
            key={card.day_number}
            className="relative z-10"
          >
            {/* Day header with icon — observed for scroll→map sync */}
            <button
              ref={(el) => {
                if (el) dayHeaderRefs.current.set(card.day_number, el);
              }}
              data-day={card.day_number}
              type="button"
              onClick={() => onDayClick?.(card.day_number)}
              onMouseEnter={() => !document.body.hasAttribute('data-dnd-active') && onDayHover?.(card.day_number)}
              onMouseLeave={() => !document.body.hasAttribute('data-dnd-active') && onDayHover?.(null)}
              className="flex items-center gap-4 w-full text-left group mb-4"
            >
              {/* Icon node on thread */}
              <div
                className={cn(
                  'timeline-node flex-shrink-0 w-9 h-9 rounded-full border flex items-center justify-center transition-colors',
                  isSafety
                    ? 'bg-zinc-500/10 dark:bg-zinc-500/15 border-zinc-500/50 dark:border-zinc-500/40 text-zinc-600 dark:text-zinc-400'
                    : 'bg-white dark:bg-zinc-950 border-zinc-300/50 dark:border-white/20 text-zinc-500 dark:text-zinc-400 group-hover:border-emerald-500 group-hover:text-emerald-600 dark:group-hover:text-emerald-400'
                )}
              >
                <DayIcon className="w-4 h-4" />
              </div>

              {/* Day title */}
              <div className="flex-1 min-w-0">
                <h3
                  className={cn(
                    'font-semibold tracking-tight',
                    'text-lg',
                    isSafety ? 'text-zinc-500 dark:text-zinc-400' : 'text-zinc-900 dark:text-white'
                  )}
                >
                  Day {card.day_number}
                  {card.date && (
                    <span className="text-sm font-normal text-zinc-500 dark:text-zinc-400 ml-2">
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
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 truncate">{card.label}</p>
                )}
                {card.subtitle && (
                  <p className="text-xs text-zinc-400 dark:text-zinc-500 truncate">{card.subtitle}</p>
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
              <div className="space-y-4 pl-[52px]">
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
                      {(() => {
                          // Build excluded category set from two sources:
                          // 1. Buffer blocks on this day (same-day exclusion)
                          // 2. Adjacent day specialist types (forward/reverse cross-domain)
                          const excludedByConstraint = new Set<string>();
                          for (const buf of bufferBlocks) {
                            const st = (buf.specialist_type || '').toLowerCase();
                            if (st && BUFFER_EXCLUSIONS[st]) {
                              BUFFER_EXCLUSIONS[st].forEach(cat => excludedByConstraint.add(cat));
                            }
                          }
                          const adjDays = dayCards.filter(
                            dc => Math.abs(dc.day_number - card.day_number) === 1
                          );
                          for (const adjDay of adjDays) {
                            for (const adjBlock of adjDay.blocks) {
                              const st = (adjBlock.specialist_type || '').toLowerCase();
                              if (st && ADJACENT_EXCLUSIONS[st]) {
                                ADJACENT_EXCLUSIONS[st].forEach(cat => excludedByConstraint.add(cat));
                              }
                            }
                          }
                          const filteredCategories = categories
                            ? categories.filter(c => !excludedByConstraint.has(c.toLowerCase()))
                            : undefined;
                          // A day is a "constraint buffer" when it has buffer blocks AND
                          // every user-selected activity type is excluded by constraints.
                          // On such days: suppress chips + auto-generate CTA; show Browse instead.
                          const isConstraintBuffer = bufferBlocks.length > 0
                            && !!categories
                            && categories.length > 0
                            && filteredCategories?.length === 0;
                          const chipsToShow = (categories && categories.length > 1 && !isConstraintBuffer)
                            ? filteredCategories?.map(c => ({
                                value: c,
                                label: c.charAt(0).toUpperCase() + c.slice(1),
                                icon: CATEGORY_ICONS[c.toLowerCase()] ?? '\u{1F3AF}',
                              }))
                            : undefined;
                          return (
                            <FreeDayCard
                              dayNumber={card.day_number}
                              dayDate={card.date ?? null}
                              destination={destination}
                              availableCategories={chipsToShow}
                              isConstraintBuffer={isConstraintBuffer}
                              onBrowse={() => {
                                setBrowseSheetDay({ dayNumber: card.day_number, date: card.date ?? null });
                                setBrowseSheetOpen(true);
                              }}
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
                          );
                        })()}
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
                              const isFreeDay = ['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
                                keyword => activityLower.includes(keyword) || summaryLower.includes(keyword)
                              );
                              if (isFreeDay) return null;
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
                                  💡 {constraint}
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
    {destination && (
      <BrowseActivitiesSheet
        open={browseSheetOpen}
        onOpenChange={setBrowseSheetOpen}
        destination={destination}
        dayNumber={browseSheetDay?.dayNumber}
        date={browseSheetDay?.date}
        stashedTiles={browseableActivities.length > 0 ? browseableActivities : undefined}
        onSelectActivity={handleSelectActivity}
      />
    )}
    </>
  );
}

export default TimelineThread;
