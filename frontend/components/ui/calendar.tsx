'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import * as React from 'react';
import { DayPicker } from 'react-day-picker';

import { cn } from '@/lib/utils';

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

// Navigation button styles - Booking.com style
const navButtonClass = cn(
  'h-8 w-8 inline-flex items-center justify-center rounded-full',
  'bg-transparent hover:bg-zinc-700/50',
  'text-zinc-400 hover:text-white transition-colors',
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
      className={cn('p-3', className)}
      classNames={{
        // Months container - side by side
        months: 'flex gap-8 relative',
        // Individual month
        month: 'space-y-4',
        // Month header with name
        month_caption: 'flex justify-center pt-1 items-center h-8',
        caption_label: 'text-sm font-semibold text-foreground',
        // Navigation - positioned at outer edges
        nav: 'absolute inset-x-0 top-0 flex items-center justify-between px-2 h-8 z-10',
        button_previous: navButtonClass,
        button_next: navButtonClass,
        // Grid
        month_grid: 'w-full border-collapse',
        weekdays: 'flex',
        weekday: 'text-muted-foreground w-10 font-medium text-[0.75rem] pb-2',
        week: 'flex w-full',
        // Day cells
        day: cn(
          'h-10 w-10 text-center text-sm p-0 relative',
          '[&:has([aria-selected].day-range-end)]:rounded-r-full',
          '[&:has([aria-selected].day-range-start)]:rounded-l-full',
          '[&:has([aria-selected])]:bg-accent',
          'first:[&:has([aria-selected])]:rounded-l-full',
          'last:[&:has([aria-selected])]:rounded-r-full'
        ),
        day_button: cn(
          'h-10 w-10 p-0 font-normal inline-flex items-center justify-center',
          'rounded-full text-sm transition-colors',
          'hover:bg-zinc-700 hover:text-white',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          'aria-selected:opacity-100'
        ),
        // Range styles
        range_start: 'day-range-start rounded-l-full bg-primary',
        range_end: 'day-range-end rounded-r-full bg-primary',
        range_middle: 'aria-selected:bg-accent aria-selected:text-accent-foreground rounded-none',
        // States
        selected: 'bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground',
        today: 'text-primary font-bold',
        outside: 'day-outside text-muted-foreground/40 aria-selected:bg-accent/50',
        disabled: 'text-muted-foreground/30',
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
