/**
 * DatesSheet
 *
 * Sheet for setting travel dates using a range picker.
 * Shows computed nights count.
 */

'use client';

import { addDays, differenceInDays, format, isBefore, startOfDay } from 'date-fns';
import { Calendar } from 'lucide-react';
import { memo, useCallback, useEffect, useState } from 'react';
import { DateRange } from 'react-day-picker';

import { Calendar as CalendarComponent } from '@/components/ui/calendar';
import { useToast } from '@/components/ui/toast';
import { cn } from '@/lib/utils';

import { BaseSheet } from './BaseSheet';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface DatesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  startDate?: Date | null;
  endDate?: Date | null;
  onSave: (startDate: Date, endDate: Date) => void;
}

// Quick presets
const DATE_PRESETS = [
  { label: 'This weekend', getDates: () => getThisWeekend() },
  { label: 'Next weekend', getDates: () => getNextWeekend() },
  { label: '1 week', getDates: () => getWeekFromNow(1) },
  { label: '2 weeks', getDates: () => getWeekFromNow(2) },
];

function getThisWeekend(): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  const dayOfWeek = today.getDay();
  const daysUntilSaturday = (6 - dayOfWeek + 7) % 7 || 7;
  const saturday = addDays(today, daysUntilSaturday);
  const sunday = addDays(saturday, 1);
  return { from: saturday, to: sunday };
}

function getNextWeekend(): { from: Date; to: Date } {
  const thisWeekend = getThisWeekend();
  return { from: addDays(thisWeekend.from, 7), to: addDays(thisWeekend.to, 7) };
}

function getWeekFromNow(weeks: number): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  const from = addDays(today, 1);
  const to = addDays(from, weeks * 7 - 1);
  return { from, to };
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function DatesSheetInner({
  open,
  onOpenChange,
  startDate,
  endDate,
  onSave,
}: DatesSheetProps) {
  const { toast } = useToast();
  const [range, setRange] = useState<DateRange | undefined>(undefined);
  // Track if user is starting a new selection (clicked once, waiting for second click)
  const [_isSelectingNewRange, setIsSelectingNewRange] = useState(false);

  // Initialize from props when opened
  useEffect(() => {
    if (open) {
      if (startDate && endDate) {
        setRange({ from: startDate, to: endDate });
      } else {
        setRange(undefined);
      }
      setIsSelectingNewRange(false);
    }
  }, [open, startDate, endDate]);

  // Computed nights
  const nights = range?.from && range?.to ? differenceInDays(range.to, range.from) : 0;

  // Format date range for display
  const formatDateRange = useCallback((from: Date, to: Date): string => {
    const fromStr = format(from, 'MMM d');
    const toStr = format(to, 'MMM d');
    return `${fromStr}–${toStr}`;
  }, []);

  // Handle save
  const handleSave = useCallback(() => {
    if (!range?.from || !range?.to) return;

    onSave(range.from, range.to);
    toast(`Dates set: ${formatDateRange(range.from, range.to)}`);
    onOpenChange(false);
  }, [range, onSave, toast, formatDateRange, onOpenChange]);

  // Handle preset click
  const handlePreset = useCallback((preset: typeof DATE_PRESETS[0]) => {
    const { from, to } = preset.getDates();
    setRange({ from, to });
  }, []);

  // Handle calendar select
  // react-day-picker v9 range mode behavior:
  // - Click 1: sets 'from' (start date)
  // - Click 2: sets 'to' (end date), completing the range
  // - Click when range is complete: resets to new 'from'
  const handleSelect = useCallback((newRange: DateRange | undefined) => {
    // Track selection state for UI feedback
    if (newRange?.from && !newRange?.to) {
      setIsSelectingNewRange(true);
    } else {
      setIsSelectingNewRange(false);
    }
    setRange(newRange);
  }, []);

  const canSave = range?.from && range?.to;
  const today = startOfDay(new Date());

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Dates"
      hint="When are you traveling?"
      maxWidth="2xl"
      footer={
        <div className="flex items-center justify-between">
          <div className="text-sm text-[var(--theme-text-muted)]">
            {nights > 0 ? (
              <span>
                <Calendar className="inline h-4 w-4 mr-1" />
                {nights} night{nights !== 1 ? 's' : ''}
              </span>
            ) : (
              <span>Select dates</span>
            )}
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className={cn(
                'px-4 py-2.5 rounded-lg text-sm font-medium',
                'border border-[var(--theme-border)]',
                'text-[var(--theme-text-muted)]',
                'hover:bg-[var(--theme-overlay)]',
                'transition-colors'
              )}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!canSave}
              className={cn(
                'px-4 py-2.5 rounded-lg text-sm font-medium',
                'transition-colors',
                canSave
                  ? 'bg-amber-500 text-white hover:bg-amber-600'
                  : 'bg-zinc-200 text-zinc-400 dark:bg-zinc-800 dark:text-zinc-600 cursor-not-allowed'
              )}
            >
              Save
            </button>
          </div>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Quick presets */}
        <div className="flex flex-wrap gap-2">
          {DATE_PRESETS.map((preset) => (
            <button
              key={preset.label}
              type="button"
              onClick={() => handlePreset(preset)}
              className={cn(
                'px-3 py-1.5 rounded-full text-sm',
                'bg-[var(--theme-overlay)] border border-[var(--theme-border)]',
                'text-[var(--theme-text)]',
                'hover:border-amber-500/50 hover:bg-amber-500/10',
                'transition-colors'
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>

        {/* Calendar - Booking.com style with 2 months */}
        <div className="flex justify-center">
          <CalendarComponent
            mode="range"
            selected={range}
            onSelect={handleSelect}
            numberOfMonths={2}
            disabled={(date) => isBefore(date, today)}
            className="rounded-lg border border-[var(--theme-border)] p-4"
          />
        </div>

        {/* Selected range display */}
        {range?.from && (
          <div className="text-center text-sm text-[var(--theme-text)]">
            {range.to ? (
              <>
                {format(range.from, 'EEEE, MMM d')} – {format(range.to, 'EEEE, MMM d')}
              </>
            ) : (
              <span className="text-amber-500">
                {format(range.from, 'EEEE, MMM d')} – Select end date
              </span>
            )}
          </div>
        )}
      </div>
    </BaseSheet>
  );
}

export const DatesSheet = memo(DatesSheetInner);

export default DatesSheet;
