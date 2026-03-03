'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */

import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useMapSync } from '@/hooks/useMapSync';
import { apiFetch } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { useUIStore } from '@/state/uiStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { BrowseActivitiesSheet } from './BrowseActivitiesSheet';
import { InlineDatePrompt } from './timeline/InlineDatePrompt';
import { useTimelineFillDay } from './timeline/useTimelineFillDay';
import { TimelineDayCard } from './TimelineDayCard';

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
    badge: null,
    badgeClass: '',
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
   * Use this to inject a DroppableDay zone that covers the full day -- including
   * free/empty days where blockWrapper never fires.
   *
   * Note: for free days, prefer `freeDayDropSlot` instead -- it renders a dedicated
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
  // Compute effective variant: prefer explicit variant, fall back to isDraft for backward compatibility
  const effectiveVariant: TimelineVariant = variant ?? (isDraft ? 'draft' : 'real');
  const { badge, badgeClass } = variantConfig[effectiveVariant];

  // Bidirectional map<->card hover sync -- DOM-based to avoid full-tree re-renders.
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
      const updatedDayCards = (doc.day_cards ?? []).map((dc) =>
        dc.day_number === targetDay ? result.day_card : dc
      );
      useDocumentStore.setState({ document: { ...doc, day_cards: updatedDayCards }, version: result.version });
    } catch {
      // Silent fail -- the itinerary wasn't modified
    }
  }, [browseSheetDay]);

  const handleBrowse = useCallback((dayNumber: number, date: string | null) => {
    setBrowseSheetDay({ dayNumber, date });
    setBrowseSheetOpen(true);
  }, []);

  const sortedDays = useMemo(() => {
    return [...dayCards].sort((a, b) => a.day_number - b.day_number);
  }, [dayCards]);

  // -- Map sync: day header refs for IntersectionObserver -----
  // Only active for variant="real" -- ghost/draft have no stable block IDs.
  const dayHeaderRefs = useRef<Map<number, HTMLElement>>(new Map());
  const scrollContainerRef = useRef<HTMLElement | null>(null);

  const dayHeaderRef = useCallback((dayNumber: number, el: HTMLElement | null) => {
    if (el) {
      dayHeaderRefs.current.set(dayNumber, el);
    }
  }, []);

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

  // -- Map sync: listen for pin-click scroll requests -----
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

      {sortedDays.map((card, index) => (
        <TimelineDayCard
          key={card.day_number}
          card={card}
          index={index}
          totalDays={sortedDays.length}
          dayCards={dayCards}
          onDayClick={onDayClick}
          onDayHover={onDayHover}
          onBrowse={handleBrowse}
          dayHeaderRef={dayHeaderRef}
          useRichBlocks={useRichBlocks}
          activeBlockId={activeBlockId}
          showPriceEstimates={showPriceEstimates}
          mode={mode}
          savedTileIds={savedTileIds}
          preferredTileIds={preferredTileIds}
          onOpenBookingDrawer={onOpenBookingDrawer}
          onUnassignTile={onUnassignTile}
          onOpenStaysSettings={onOpenStaysSettings}
          onOpenFlightsSettings={onOpenFlightsSettings}
          onRemoveBlock={onRemoveBlock}
          blockWrapper={blockWrapper}
          dayWrapper={dayWrapper}
          freeDayDropSlot={freeDayDropSlot}
          destination={destination}
          categories={categories}
          fillingDay={fillingDay}
          fillDayRejection={fillDayRejection}
          handleFillDay={handleFillDay}
          disableFillDayActions={disableFillDayActions}
        />
      ))}
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
