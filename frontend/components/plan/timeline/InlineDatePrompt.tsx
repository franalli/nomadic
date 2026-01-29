/**
 * InlineDatePrompt
 *
 * Inline prompt shown at top of Timeline when dates are missing.
 * Replaces modal-based TripLengthSheet for better flow continuity.
 *
 * Two states:
 * 1. No start_date: "When are you traveling?" + "Set travel dates" button
 * 2. Has start_date but no duration: Quick picks (3/5/7/10 nights) + "Or pick specific dates"
 */

'use client';

import { CalendarDays } from 'lucide-react';

import { cn } from '@/lib/utils';

// Quick pick options matching TripLengthSheet
const QUICK_PICKS = [
  { nights: 3, label: '3 nights' },
  { nights: 5, label: '5 nights' },
  { nights: 7, label: '7 nights' },
  { nights: 10, label: '10 nights' },
];

interface InlineDatePromptProps {
  /** Start date in ISO format (yyyy-MM-dd) or null */
  startDate: string | null;
  /** Called when user selects a quick pick nights option */
  onSelectNights: (nights: number) => void;
  /** Called when user wants to open the full date picker */
  onOpenDatePicker: () => void;
}

export function InlineDatePrompt({
  startDate,
  onSelectNights,
  onOpenDatePicker,
}: InlineDatePromptProps) {
  // If no start date, prompt for dates first
  if (!startDate) {
    return (
      <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-6 mb-6">
        <div className="flex items-center gap-3 mb-4">
          <CalendarDays className="h-5 w-5 text-emerald-500" />
          <h3 className="font-medium text-foreground">When are you traveling?</h3>
        </div>
        <button
          type="button"
          onClick={onOpenDatePicker}
          className={cn(
            'w-full flex items-center justify-center gap-2 p-3 rounded-lg',
            'bg-emerald-500 text-white font-medium',
            'hover:bg-emerald-600 transition-colors'
          )}
        >
          <CalendarDays className="h-4 w-4" />
          Set travel dates
        </button>
      </div>
    );
  }

  // Has start date but no duration - show quick picks
  return (
    <div className="bg-muted/30 border border-border rounded-xl p-6 mb-6">
      <div className="flex items-center gap-3 mb-2">
        <CalendarDays className="h-5 w-5 text-muted-foreground" />
        <h3 className="font-medium text-foreground">How long is your trip?</h3>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        Set trip length to generate your day-by-day itinerary
      </p>

      {/* Quick picks grid */}
      <div className="grid grid-cols-4 gap-2 mb-3">
        {QUICK_PICKS.map(({ nights, label }) => (
          <button
            key={nights}
            type="button"
            onClick={() => onSelectNights(nights)}
            className={cn(
              'py-2 px-3 rounded-lg text-sm font-medium',
              'bg-card border border-border',
              'hover:border-emerald-500/50 hover:bg-emerald-500/5',
              'transition-colors'
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Custom dates link */}
      <button
        type="button"
        onClick={onOpenDatePicker}
        className="text-sm text-primary hover:underline"
      >
        Or pick specific dates
      </button>
    </div>
  );
}

export default InlineDatePrompt;
