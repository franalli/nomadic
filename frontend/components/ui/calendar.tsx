'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import * as React from 'react';
import { DayPicker } from 'react-day-picker';

import { cn } from '@/lib/utils';

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

// Navigation button styles - Light + Dark mode
const navButtonClass = cn(
  'h-8 w-8 inline-flex items-center justify-center rounded-full',
  'transition-all duration-200',
  // Light: Subtle white with border
  'bg-white hover:bg-zinc-100 border border-zinc-200',
  'text-zinc-400 hover:text-zinc-900',
  // Dark: Glass style
  'dark:bg-white/5 dark:hover:bg-white/10 dark:border-white/10',
  'dark:text-zinc-400 dark:hover:text-white',
  'disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent'
);

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
        // Months container - MORE space between months (space-x-10)
        months: 'flex flex-col sm:flex-row space-y-4 sm:space-x-10 sm:space-y-0 relative',
        // Individual month - more vertical breathing room
        month: 'space-y-4',
        // Month header - premium uppercase with bottom margin
        month_caption: 'flex justify-center pt-1 items-center h-8 mb-4',
        caption_label: 'text-xs font-bold text-zinc-700 dark:text-zinc-300 tracking-widest uppercase',
        // Navigation - positioned at outer edges
        nav: 'absolute inset-x-0 top-0 flex items-center justify-between px-2 h-8 z-10',
        button_previous: navButtonClass,
        button_next: navButtonClass,
        // Grid
        month_grid: 'w-full border-collapse',
        weekdays: 'flex',
        weekday: 'text-zinc-500 w-9 font-normal text-[0.7rem] pb-2 uppercase tracking-wider',
        week: 'flex w-full',
        // Day cells - Black strip (Light) / Emerald strip (Dark)
        day: cn(
          'h-9 w-9 text-center text-sm p-0 relative',
          '[&:has([aria-selected].day-range-end)]:rounded-r-md',
          '[&:has([aria-selected].day-range-start)]:rounded-l-md',
          // Range middle background: Light grey (Light) / Emerald tint (Dark)
          '[&:has([aria-selected])]:bg-zinc-100 dark:[&:has([aria-selected])]:bg-emerald-500/10',
          'first:[&:has([aria-selected])]:rounded-l-md',
          'last:[&:has([aria-selected])]:rounded-r-md'
        ),
        day_button: cn(
          'h-9 w-9 p-0 font-medium inline-flex items-center justify-center',
          'rounded-full text-sm transition-all duration-200',
          // Base text color: Dark grey (Light) / Light grey (Dark)
          'text-zinc-600 dark:text-zinc-400',
          'hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-white/10 dark:hover:text-white',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/50',
          'aria-selected:opacity-100'
        ),
        // Range styles - Black Ink (Light) / Emerald Glow (Dark)
        range_start: cn(
          'day-range-start',
          // Light: Solid Black / Dark: Emerald
          '!bg-zinc-900 !text-white dark:!bg-emerald-500',
          'shadow-lg shadow-zinc-900/20 dark:shadow-[0_0_15px_-3px_rgba(16,185,129,0.5)]'
        ),
        range_end: cn(
          'day-range-end',
          // Light: Solid Black / Dark: Emerald
          '!bg-zinc-900 !text-white dark:!bg-emerald-500',
          'shadow-lg shadow-zinc-900/20 dark:shadow-[0_0_15px_-3px_rgba(16,185,129,0.5)]'
        ),
        range_middle: cn(
          // Light: Light grey strip / Dark: Emerald tint
          '!bg-zinc-100 !text-zinc-900 dark:!bg-emerald-900/30 dark:!text-emerald-200',
          '!rounded-none'
        ),
        // States
        selected: cn(
          // Light: Solid Black / Dark: Emerald
          '!bg-zinc-900 !text-white dark:!bg-emerald-500',
          'hover:!bg-zinc-800 dark:hover:!bg-emerald-400',
          'shadow-lg shadow-zinc-900/20 dark:shadow-[0_0_15px_-3px_rgba(16,185,129,0.5)]'
        ),
        today: cn(
          // Light: Subtle border / Dark: Dark background
          'bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white',
          'border-b-2 border-zinc-900 dark:border-white/20 rounded-full'
        ),
        outside: cn(
          'day-outside text-zinc-400/50 dark:text-zinc-700/40',
          'aria-selected:!bg-zinc-100/50 dark:aria-selected:!bg-emerald-500/5'
        ),
        disabled: 'text-zinc-300 dark:text-zinc-700/30 cursor-not-allowed',
        hidden: 'invisible',
        ...classNames,
      }}
      components={{
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
