'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */

import type { ReactNode } from 'react';
import { useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

import { BrowseActivitiesSheet } from './BrowseActivitiesSheet';
import { InlineDatePrompt } from './timeline/InlineDatePrompt';
import { useTimelineFillDay } from './timeline/useTimelineFillDay';
import { TimelineDayCard } from './TimelineDayCard';
import { useTimelineThreadBrowseSheet } from './useTimelineThreadBrowseSheet';
import { useTimelineThreadMapSync } from './useTimelineThreadMapSync';

export type TimelineVariant = 'ghost' | 'draft' | 'real';

const variantConfig: Record<TimelineVariant, { badge: string | null; badgeClass: string }> = {
  ghost: {
    badge: 'Specialist Preview',
    badgeClass: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  draft: { badge: null, badgeClass: '' },
  real: { badge: null, badgeClass: '' },
};

interface TimelineThreadProps {
  dayCards: DayCard[];
  expandedDay?: number | null;
  onDayClick?: (dayNumber: number) => void;
  showPriceEstimates?: boolean;
  activeBlockId?: string | null;
  isDraft?: boolean;
  variant?: TimelineVariant;
  hasDuration?: boolean;
  startDate?: string | null;
  onSelectNights?: (nights: number) => void;
  onOpenDatePicker?: () => void;
  onDayHover?: (dayNumber: number | null) => void;
  onOpenBookingDrawer?: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onUnassignTile?: (blockId: string) => void;
  savedTileIds?: Set<string>;
  useRichBlocks?: boolean;
  mode?: 'planning' | 'booking';
  preferredTileIds?: Set<string>;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  disableFillDayActions?: boolean;
  onRemoveBlock?: (blockId: string, dayNumber: number) => void;
  blockWrapper?: (block: DayBlock, dayNumber: number, children: ReactNode) => ReactNode;
  dayWrapper?: (dayNumber: number, children: ReactNode) => ReactNode;
  freeDayDropSlot?: (dayNumber: number) => ReactNode;
}

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
  onDayHover,
  onOpenBookingDrawer,
  onUnassignTile,
  savedTileIds,
  useRichBlocks = false,
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
  const effectiveVariant: TimelineVariant = variant ?? (isDraft ? 'draft' : 'real');
  const { badge, badgeClass } = variantConfig[effectiveVariant];
  const { destination, categories } = useDocumentStore(
    useShallow((store) => ({
      destination: store.document?.trip_inputs?.destination ?? null,
      categories: store.document?.trip_inputs?.activity_settings?.categories,
    }))
  );
  const { fillingDay, fillDayRejection, handleFillDay } = useTimelineFillDay({
    disableFillDayActions,
    categories,
  });
  const sortedDays = useMemo(
    () => [...dayCards].sort((a, b) => a.day_number - b.day_number),
    [dayCards]
  );
  const dayHeaderRef = useTimelineThreadMapSync(
    sortedDays.map((day) => day.day_number),
    effectiveVariant
  );
  const {
    browseSheetOpen,
    browseSheetDay,
    browseableActivities,
    setBrowseSheetOpen,
    handleBrowse,
    handleSelectActivity,
  } = useTimelineThreadBrowseSheet();

  if (sortedDays.length === 0) {
    return (
      <div className="rounded-xl border-2 border-dashed border-zinc-200 py-12 text-center text-zinc-500 dark:border-white/10 dark:text-zinc-400">
        Generating your itinerary...
      </div>
    );
  }

  return (
    <>
      <div className="timeline-thread relative space-y-8 pl-4 pr-2 py-6">
        {badge && (
          <div className="absolute top-2 right-2 z-10">
            <span
              className={cn(
                'rounded-full border border-zinc-200/50 px-2 py-1 text-xs font-medium dark:border-white/10',
                badgeClass
              )}
            >
              {badge}
            </span>
          </div>
        )}

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
