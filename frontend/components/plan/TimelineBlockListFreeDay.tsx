'use client';

import type { ReactNode } from 'react';

import type { DayBlock } from '@/types/plan-envelope';

import { FreeDayCard } from './timeline/blocks/FreeDayCard';
import { SafetyBlock } from './timeline/blocks/SafetyBlock';

interface TimelineBlockListFreeDayProps {
  dayNumber: number;
  date: string | null | undefined;
  bufferBlocks: DayBlock[];
  destination: string | null;
  chipsToShow: Array<{ value: string; label: string; icon: string }> | undefined;
  isConstraintBuffer: boolean;
  fillingDay: number | null;
  disableFillDayActions: boolean;
  fillDayRejection: { dayNumber: number; reason: string } | null;
  onFillDay: (dayNumber: number, dayDate: string | null, categories?: string[]) => Promise<void>;
  onBrowse: (dayNumber: number, date: string | null) => void;
  freeDayDropSlot?: ReactNode;
}

export function TimelineBlockListFreeDay({
  dayNumber,
  date,
  bufferBlocks,
  destination,
  chipsToShow,
  isConstraintBuffer,
  fillingDay,
  disableFillDayActions,
  fillDayRejection,
  onFillDay,
  onBrowse,
  freeDayDropSlot,
}: TimelineBlockListFreeDayProps) {
  return (
    <>
      {bufferBlocks.map((block, index) => (
        <SafetyBlock
          key={`${dayNumber}-buf-${index}`}
          reason={
            block.buffer_reason ||
            (block.buffer_type === 'no_fly'
              ? '24h no-fly buffer before flight'
              : 'Rest day recommended')
          }
          until={block.buffer_type === 'no_fly' ? block.scheduled_time : undefined}
          type={block.buffer_type as 'no_fly' | 'rest_day' | 'acclimatization' | undefined}
        />
      ))}
      <FreeDayCard
        dayNumber={dayNumber}
        dayDate={date ?? null}
        destination={destination}
        availableCategories={chipsToShow}
        isConstraintBuffer={isConstraintBuffer}
        onBrowse={() => onBrowse(dayNumber, date ?? null)}
        onFillDay={isConstraintBuffer ? undefined : onFillDay}
        isFilling={fillingDay === dayNumber}
        isDisabled={disableFillDayActions}
        rejectionMessage={
          fillDayRejection?.dayNumber === dayNumber ? fillDayRejection.reason : undefined
        }
        dropZoneSlot={freeDayDropSlot}
      />
    </>
  );
}
