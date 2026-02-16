/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import * as React from 'react';
import { type DayButtonProps,DayPicker } from 'react-day-picker';

import { cn } from '@/lib/utils';

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

// Navigation button styles
const navButtonClass = cn(
  'h-8 w-8 inline-flex items-center justify-center rounded-lg',
  'transition-all duration-200',
  'bg-white hover:bg-zinc-100 border border-zinc-200',
  'text-zinc-500 hover:text-zinc-900',
  'dark:bg-white/5 dark:hover:bg-white/10 dark:border-white/10',
  'dark:text-zinc-400 dark:hover:text-white',
  'disabled:opacity-30 disabled:cursor-not-allowed'
);

// Custom DayButton with explicit priority-based styling (no CSS specificity issues)
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function CustomDayButton({ day, modifiers, className, ...props }: DayButtonProps) {
  const isRangeStart = modifiers?.range_start;
  const isRangeEnd = modifiers?.range_end;
  const isRangeMiddle = modifiers?.range_middle;
  const isSelected = modifiers?.selected;
  const isToday = modifiers?.today;
  const isOutside = modifiers?.outside;
  const isDisabled = modifiers?.disabled;

  // Priority-based styling (JS logic, not CSS specificity)
  const getStyles = () => {
    // Disabled state
    if (isDisabled) {
      return 'text-zinc-400 opacity-50 cursor-not-allowed';
    }

    // Outside month (faded)
    if (isOutside) {
      return 'text-zinc-400 dark:text-zinc-600 opacity-50';
    }

    // PRIORITY 1: Range endpoints (Caps - emerald with contrasting text, extra-bold)
    if (isRangeStart && isRangeEnd) {
      // Single day range (both start and end)
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-md font-extrabold';
    }
    if (isRangeStart) {
      // Left cap: rounded left, sharp right
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-l-md rounded-r-none font-extrabold';
    }
    if (isRangeEnd) {
      // Right cap: sharp left, rounded right
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-r-md rounded-l-none font-extrabold';
    }

    // PRIORITY 2: Range middle (Bridge - neutral zinc for contrast)
    // Must come BEFORE isSelected check since all range dates have selected=true
    if (isRangeMiddle) {
      return 'bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100 rounded-none';
    }

    // PRIORITY 3: Single selection (solid emerald, extra-bold)
    if (isSelected) {
      return 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-zinc-950 rounded-md font-extrabold';
    }

    // PRIORITY 4: Today (extra-bold emerald text + 2px underline, NO background)
    if (isToday) {
      return 'text-emerald-600 dark:text-emerald-400 font-extrabold underline decoration-2 decoration-emerald-600 dark:decoration-emerald-400 underline-offset-4 bg-transparent';
    }

    // Default: zinc text
    return 'text-zinc-900 dark:text-zinc-100';
  };

  return (
    <button
      {...props}
      className={cn(
        // Base styles with tabular nums for vertical alignment
        'h-9 w-9 p-0 font-medium inline-flex items-center justify-center',
        'rounded-none text-sm tracking-tight tabular-nums',
        'transition-all duration-150 ease-in-out',
        // Hover: zinc-200 square, 0px radius (only when not in a selected/range state)
        !isRangeStart && !isRangeEnd && !isSelected && !isRangeMiddle && 'hover:bg-zinc-200 dark:hover:bg-zinc-800',
        // Priority-based styles
        getStyles(),
        className
      )}
    />
  );
}

function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  numberOfMonths = 2,
  ...props
}: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      numberOfMonths={numberOfMonths}
      className={cn('p-0', className)}
      classNames={{
        months: 'flex flex-col sm:flex-row space-y-4 sm:space-x-10 sm:space-y-0 relative',
        month: 'space-y-4',
        month_caption: 'flex justify-center pt-1 items-center h-8 mb-4',
        caption_label: 'text-sm font-semibold text-zinc-900 dark:text-zinc-100',
        nav: 'absolute inset-x-0 top-0 flex items-center justify-between px-2 h-8 z-10',
        button_previous: navButtonClass,
        button_next: navButtonClass,
        month_grid: 'w-full border-collapse',
        weekdays: 'flex',
        // Day headers: 10px, bold, uppercase, tracking-widest (per design-system.md)
        weekday: 'text-zinc-500 dark:text-zinc-400 w-9 font-bold text-[10px] tracking-widest pb-2 uppercase',
        week: 'flex w-full mt-0.5',
        day: 'h-9 w-9 text-center text-sm p-0 relative',
        // Minimal classNames - actual styling handled by CustomDayButton
        day_button: '',
        range_start: '',
        range_end: '',
        range_middle: '',
        selected: '',
        today: '',
        outside: '',
        disabled: '',
        hidden: 'invisible',
        ...classNames,
      }}
      components={{
        DayButton: CustomDayButton,
        PreviousMonthButton: (props) => (
          <button {...props} className={navButtonClass}>
            <ChevronLeft className="h-5 w-5" />
          </button>
        ),
        NextMonthButton: (props) => (
          <button {...props} className={navButtonClass}>
            <ChevronRight className="h-5 w-5" />
          </button>
        ),
      }}
      {...props}
    />
  );
}
Calendar.displayName = 'Calendar';

export { Calendar };
