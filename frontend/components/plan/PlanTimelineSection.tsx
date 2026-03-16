'use client';

/**
 * PlanTimelineSection
 *
 * Timeline section rendering for full-density plan view.
 * Handles DnD wrapping, skeleton loading, and regeneration overlay.
 */

import { AnimatePresence, LayoutGroup, motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import { type ReactNode, useCallback } from 'react';

import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useToast } from '@/components/ui/toast';
import { REVEAL_TIMING } from '@/lib/animation-config';
import { debugLog } from '@/lib/debug';
import { showMutationToast } from '@/lib/showMutationToast';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { DraggableBlock } from './timeline/DraggableBlock';
import { DroppableDay } from './timeline/DroppableDay';
import { FreeDayDropSlot } from './timeline/FreeDayDropSlot';
import { ItineraryDndWrapper } from './timeline/ItineraryDndWrapper';
import { TimelineSkeleton } from './timeline/TimelineSkeleton';
import { TimelineThread, type TimelineVariant } from './TimelineThread';

// Extracted animation constants to avoid re-creating objects on every render
const FADE_INITIAL = { opacity: 0 } as const;
const FADE_VISIBLE = { opacity: 1 } as const;
const FADE_EXIT = { opacity: 0 } as const;
const SKELETON_TRANSITION = { duration: 0.2 } as const;
const TIMELINE_LOADING_ROWS = [1, 2] as const;

interface PlanTimelineSectionProps {
  dayCards: DayCard[];
  timelineVariant: TimelineVariant;
  isStreaming: boolean;
  isRegenUpdating: boolean;
  isExpandingItinerary: boolean;
  hasItineraryContent: boolean;
  preferenceCount: number;
  savedTileIds: Set<string>;
  timelineSectionRef: React.RefObject<HTMLDivElement | null>;
  handleOpenBookingDrawer: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
}

function TimelineLoadingState({ overlay = false }: { overlay?: boolean }): ReactNode {
  return (
    <div
      aria-live="polite"
      className={cn(
        'space-y-4',
        overlay
          ? 'rounded-2xl border border-zinc-200/60 bg-white/90 p-4 shadow-soft backdrop-blur-sm dark:border-white/10 dark:bg-zinc-950/80'
          : 'px-4 py-6 animate-pulse'
      )}
    >
      {TIMELINE_LOADING_ROWS.map((i) => (
        <div key={i} className="space-y-2">
          <div className="h-6 w-24 rounded bg-zinc-200/50 dark:bg-zinc-700/50" />
          <div className="h-20 rounded-lg bg-zinc-200/50 dark:bg-zinc-700/50" />
          <div className="h-20 rounded-lg bg-zinc-200/50 dark:bg-zinc-700/50" />
        </div>
      ))}
      <div className="flex items-center justify-center gap-2 pt-4">
        <Loader2 className="h-4 w-4 animate-spin text-emerald-500" />
        <span className="text-sm text-zinc-500 dark:text-zinc-400">
          Building your itinerary...
        </span>
      </div>
    </div>
  );
}

export function PlanTimelineSection({
  dayCards,
  timelineVariant,
  isStreaming,
  isRegenUpdating,
  isExpandingItinerary,
  hasItineraryContent,
  preferenceCount: _preferenceCount,
  savedTileIds,
  timelineSectionRef,
  handleOpenBookingDrawer,
  onOpenStaysSettings,
  onOpenFlightsSettings,
}: PlanTimelineSectionProps): ReactNode {
  const removeBlock = useDocumentStore(s => s.removeBlock);
  const { toast } = useToast();

  const handleRemoveBlock = useCallback(async (blockId: string, dayNumber: number) => {
    try {
      await removeBlock(blockId, dayNumber);
      // Show undo toast (undo entry is set inside store.removeBlock)
      const undoEntry = useDocumentStore.getState().undoEntry;
      showMutationToast(undoEntry?.label ?? 'Activity removed', toast);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to remove block';
      debugLog('[removeBlock] error:', msg);
      toast(msg.includes('VERSION_CONFLICT') ? 'Version conflict — please retry' : 'Could not update timeline — try again', { type: 'error' });
    }
  }, [removeBlock, toast]);

  // Gate real itinerary on actual day_cards being present (Layer 3).
  // Prevents a hard layout swap when plan_view_state flips to S3 before
  // day_cards have arrived in the same envelope batch.
  const showRealItinerary = hasItineraryContent && dayCards.length > 0;
  const showSkeletonTimeline = !showRealItinerary && (isExpandingItinerary || hasItineraryContent);
  const showLoadingOverlay = showRealItinerary && isExpandingItinerary;
  const disableTimelineInteractions = isRegenUpdating || isExpandingItinerary;

  const wrapDay = useCallback(
    (dayNum: number, children: React.ReactNode) => (
      <DroppableDay dayNumber={dayNum}>{children}</DroppableDay>
    ),
    []
  );
  const renderFreeDayDropSlot = useCallback(
    (dayNum: number) => <FreeDayDropSlot dayNumber={dayNum} />,
    []
  );
  const wrapBlock = useCallback(
    (block: DayBlock, dayNum: number, children: React.ReactNode) => (
      <DraggableBlock block={block} dayNumber={dayNum}>{children}</DraggableBlock>
    ),
    []
  );

  return (
    <AnimatePresence mode="popLayout">
      {showRealItinerary ? (
        <motion.section
          key="timeline-real"
          ref={timelineSectionRef}
          initial={FADE_INITIAL}
          animate={FADE_VISIBLE}
          exit={FADE_EXIT}
          transition={{ duration: REVEAL_TIMING.TIMELINE_FADE / 1000, delay: REVEAL_TIMING.TIMELINE_DELAY / 1000, ease: [0.4, 0, 0.2, 1] }}
          id="timeline-section"
          className="relative px-4 py-4"
        >
          {showLoadingOverlay && (
            <div className="pointer-events-none absolute inset-4 z-10">
              <TimelineLoadingState overlay />
            </div>
          )}
          <div className={cn(
            "transition-opacity duration-300",
            disableTimelineInteractions && "opacity-25 pointer-events-none"
          )}>
            <LayoutGroup id="droppable-days">
              <ItineraryDndWrapper>
                <ErrorBoundary label="Timeline">
                  <TimelineThread
                    dayCards={dayCards}
                    variant={timelineVariant}
                    useRichBlocks={true}
                    disableFillDayActions={isStreaming}
                    savedTileIds={savedTileIds}
                    onOpenBookingDrawer={handleOpenBookingDrawer}
                    onOpenStaysSettings={onOpenStaysSettings}
                    onOpenFlightsSettings={onOpenFlightsSettings}
                    onRemoveBlock={handleRemoveBlock}
                    dayWrapper={wrapDay}
                    freeDayDropSlot={renderFreeDayDropSlot}
                    blockWrapper={wrapBlock}
                  />
                </ErrorBoundary>
              </ItineraryDndWrapper>
            </LayoutGroup>
          </div>
        </motion.section>
      ) : showSkeletonTimeline ? (
        <motion.section
          key="timeline-skeleton"
          ref={timelineSectionRef}
          initial={FADE_INITIAL}
          animate={FADE_VISIBLE}
          exit={FADE_EXIT}
          transition={SKELETON_TRANSITION}
          className="px-4 py-6"
        >
          <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
            Building your itinerary. Specialist preview available.
          </div>
          <TimelineSkeleton />
        </motion.section>
      ) : null}
    </AnimatePresence>
  );
}
