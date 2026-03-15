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
import { TimelineThread, type TimelineVariant } from './TimelineThread';

// Extracted animation constants to avoid re-creating objects on every render
const FADE_INITIAL = { opacity: 0 } as const;
const FADE_VISIBLE = { opacity: 1 } as const;
const FADE_EXIT = { opacity: 0 } as const;
const SKELETON_TRANSITION = { duration: 0.2 } as const;

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
          className="px-4 py-4"
        >
          <div className={cn(
            "transition-opacity duration-300",
            isRegenUpdating && "opacity-40 pointer-events-none"
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
      ) : isExpandingItinerary ? (
        <motion.section
          key="timeline-skeleton"
          ref={timelineSectionRef}
          initial={FADE_INITIAL}
          animate={FADE_VISIBLE}
          exit={FADE_EXIT}
          transition={SKELETON_TRANSITION}
          className="px-4 py-6 space-y-4 animate-pulse"
        >
          {[1, 2].map((i) => (
            <div key={i} className="space-y-2">
              <div className="h-6 w-24 bg-zinc-200/50 dark:bg-zinc-700/50 rounded" />
              <div className="h-20 bg-zinc-200/50 dark:bg-zinc-700/50 rounded-lg" />
              <div className="h-20 bg-zinc-200/50 dark:bg-zinc-700/50 rounded-lg" />
            </div>
          ))}
          <div className="flex items-center justify-center gap-2 pt-4">
            <Loader2 className="w-4 h-4 animate-spin text-emerald-500" />
            <span className="text-sm text-zinc-500 dark:text-zinc-400">Building your itinerary...</span>
          </div>
        </motion.section>
      ) : null}
    </AnimatePresence>
  );
}
