/**
 * TripLengthSheet
 *
 * Quick picks for trip duration when user tries to create itinerary without end date.
 * Shows when user clicks "Create day-by-day itinerary" but has no end_date or trip_duration set.
 */

'use client';

import { CalendarDays } from 'lucide-react';
import { memo } from 'react';

import { BaseSheet } from '@/components/planner/sheets/BaseSheet';
import { cn } from '@/lib/utils';
import { formatDateForDisplay } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface TripLengthSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  startDate: string | null | undefined; // ISO date string, may be missing
  onSelectNights: (nights: number) => void;
  onOpenDatePicker: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const QUICK_PICKS = [
  { nights: 3, label: '3 nights', description: 'Long weekend' },
  { nights: 5, label: '5 nights', description: 'Short trip' },
  { nights: 7, label: '7 nights', description: 'One week' },
  { nights: 10, label: '10 nights', description: 'Extended trip' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export const TripLengthSheet = memo(function TripLengthSheet({
  open,
  onOpenChange,
  startDate,
  onSelectNights,
  onOpenDatePicker,
}: TripLengthSheetProps) {
  // Guard: if no start date, show different content
  if (!startDate) {
    return (
      <BaseSheet
        open={open}
        onOpenChange={onOpenChange}
        title="Set a start date first"
        hint="You need a start date before setting trip length"
      >
        <div className="py-4">
          <button
            type="button"
            onClick={onOpenDatePicker}
            className={cn(
              'w-full flex items-center justify-center gap-2 p-3 rounded-lg',
              'bg-amber-600 text-white font-medium',
              'hover:bg-amber-500 transition-colors'
            )}
          >
            <CalendarDays className="h-4 w-4" />
            Set start date
          </button>
        </div>
      </BaseSheet>
    );
  }

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="How long is your trip?"
      hint="Select trip duration to create your itinerary"
    >
      <div className="space-y-4 py-2">
        <p className="text-sm text-zinc-400">
          Starting {formatDateForDisplay(startDate)}
        </p>

        {/* Quick picks */}
        <div className="grid grid-cols-2 gap-2">
          {QUICK_PICKS.map(({ nights, label, description }) => (
            <button
              key={nights}
              type="button"
              onClick={() => onSelectNights(nights)}
              className={cn(
                'flex flex-col items-start p-3 rounded-lg',
                'border border-zinc-700 bg-zinc-800/50',
                'text-left transition-colors',
                'hover:border-amber-500/50 hover:bg-amber-500/5'
              )}
            >
              <div className="font-medium text-zinc-200">{label}</div>
              <p className="text-xs text-zinc-500">{description}</p>
            </button>
          ))}
        </div>

        {/* Custom dates option */}
        <button
          type="button"
          onClick={onOpenDatePicker}
          className={cn(
            'w-full flex items-center gap-3 p-4 rounded-lg',
            'border border-zinc-700 bg-zinc-800/50',
            'text-left transition-colors',
            'hover:border-zinc-600 hover:bg-zinc-800'
          )}
        >
          <CalendarDays className="h-5 w-5 text-zinc-400" />
          <div>
            <div className="font-medium text-zinc-200">Pick specific dates</div>
            <p className="text-xs text-zinc-500">Open calendar to choose end date</p>
          </div>
        </button>

        {/* Cancel */}
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="w-full text-center text-sm text-zinc-500 hover:text-zinc-400 transition-colors"
        >
          Cancel
        </button>
      </div>
    </BaseSheet>
  );
});

export default TripLengthSheet;
