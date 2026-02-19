'use client';

/**
 * PlanTimelineSection
 *
 * Timeline section rendering for full-density plan view.
 * Handles DnD wrapping, skeleton loading, and regeneration overlay.
 */

import { LayoutGroup, motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

import { REVEAL_TIMING } from '@/lib/animation-config';
import type { DayCard } from '@/types/plan-envelope';

import { DraggableBlock } from './timeline/DraggableBlock';
import { DroppableDay } from './timeline/DroppableDay';
import { FreeDayDropSlot } from './timeline/FreeDayDropSlot';
import { ItineraryDndWrapper } from './timeline/ItineraryDndWrapper';
import { TimelineThread, type TimelineVariant } from './TimelineThread';

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
  preferenceCount,
  savedTileIds,
  timelineSectionRef,
  handleOpenBookingDrawer,
  onOpenStaysSettings,
  onOpenFlightsSettings,
}: PlanTimelineSectionProps): ReactNode {
  if (hasItineraryContent) {
    return (
      <motion.section
        key="timeline-section"
        ref={timelineSectionRef}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: REVEAL_TIMING.TIMELINE_FADE / 1000 }}
        id="timeline-section"
        className="px-4 py-4"
      >
        <div className="relative">
          <LayoutGroup id="droppable-days">
            <ItineraryDndWrapper>
              <TimelineThread
                dayCards={dayCards}
                variant={timelineVariant}
                useRichBlocks={true}
                disableFillDayActions={isStreaming}
                savedTileIds={savedTileIds}
                onOpenBookingDrawer={handleOpenBookingDrawer}
                onOpenStaysSettings={onOpenStaysSettings}
                onOpenFlightsSettings={onOpenFlightsSettings}
                dayWrapper={(dayNum, children) => (
                  <DroppableDay dayNumber={dayNum}>{children}</DroppableDay>
                )}
                freeDayDropSlot={(dayNum) => (
                  <FreeDayDropSlot dayNumber={dayNum} />
                )}
                blockWrapper={(block, dayNum, children) => (
                  <DraggableBlock block={block} dayNumber={dayNum}>
                    {children}
                  </DraggableBlock>
                )}
              />
            </ItineraryDndWrapper>
          </LayoutGroup>

          {/* Regeneration overlay — dims timeline during update */}
          {isRegenUpdating && (
            <div className="absolute inset-0 bg-black/50 z-10 flex items-center justify-center rounded-lg">
              <div className="flex items-center gap-2 text-white bg-zinc-900/80 px-4 py-2 rounded-full">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span className="text-sm">Updating with {preferenceCount} preferences...</span>
              </div>
            </div>
          )}
        </div>
      </motion.section>
    );
  }

  if (isExpandingItinerary) {
    return (
      <section ref={timelineSectionRef} className="px-4 py-6 space-y-4 animate-pulse">
        {[1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <div className="h-6 w-24 bg-zinc-200 dark:bg-zinc-800 rounded" />
            <div className="h-20 bg-zinc-200/40 dark:bg-zinc-800/40 rounded-lg" />
            <div className="h-20 bg-zinc-200/40 dark:bg-zinc-800/40 rounded-lg" />
          </div>
        ))}
        <div className="flex items-center justify-center gap-2 pt-4">
          <Loader2 className="w-4 h-4 animate-spin text-emerald-500" />
          <span className="text-sm text-muted-foreground">Building your itinerary...</span>
        </div>
      </section>
    );
  }

  return null;
}
