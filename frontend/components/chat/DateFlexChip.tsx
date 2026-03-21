'use client';

import { CalendarDays } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { DateFlexSuggestion } from '@/types/document';

interface DateFlexChipProps {
  flex: DateFlexSuggestion;
  onSendMessage: (message: string, options?: { suggestionClicked?: string }) => void;
  tripStartDate?: string | null;
  tripEndDate?: string | null;
}

function formatShortDate(dateStr: string): string {
  try {
    const [y, m, d] = dateStr.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return dateStr;
  }
}

function parseDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function addDaysToDate(dateStr: string, days: number): string {
  const dt = parseDate(dateStr);
  dt.setDate(dt.getDate() + days);
  const yy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, '0');
  const dd = String(dt.getDate()).padStart(2, '0');
  return `${yy}-${mm}-${dd}`;
}

function daysBetween(a: string, b: string): number {
  return Math.round((parseDate(b).getTime() - parseDate(a).getTime()) / 86400000);
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '\u20AC',
  GBP: '\u00A3',
  JPY: '\u00A5',
  CNY: '\u00A5',
  KRW: '\u20A9',
  INR: '\u20B9',
  THB: '\u0E3F',
  AUD: 'A$',
  CAD: 'C$',
  BRL: 'R$',
};

export function DateFlexChip({
  flex,
  onSendMessage,
  tripStartDate,
  tripEndDate,
}: DateFlexChipProps) {
  const symbol = CURRENCY_SYMBOLS[flex.currency] ?? flex.currency + ' ';

  const handleClick = () => {
    // Compute new end date by preserving trip duration
    let dateRange = formatShortDate(flex.cheapest_date);
    if (tripStartDate && tripEndDate) {
      const duration = daysBetween(tripStartDate, tripEndDate);
      const newEnd = addDaysToDate(flex.cheapest_date, duration);
      dateRange = `${formatShortDate(flex.cheapest_date)} to ${formatShortDate(newEnd)}`;
    }
    onSendMessage(`Change dates to ${dateRange}`, {
      suggestionClicked: 'date_flex_suggestion',
    });
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        'px-4 py-2.5 rounded-lg',
        'shrink-0 whitespace-nowrap',
        'text-xs font-bold uppercase tracking-wide',
        'transition-all duration-150 active:scale-95',
        'max-w-full truncate',
        'bg-emerald-50 dark:bg-emerald-950/30',
        'border-2 border-emerald-500/40 dark:border-emerald-500/30',
        'text-emerald-700 dark:text-emerald-400',
        'hover:bg-emerald-100 hover:border-emerald-500',
        'dark:hover:bg-emerald-900/40 dark:hover:border-emerald-400/50',
      )}
    >
      <CalendarDays className="w-3 h-3 mr-1.5 inline-block" />
      Save {symbol}{flex.savings}
      <span className="ml-1 opacity-70 normal-case font-medium">
        — fly {formatShortDate(flex.cheapest_date)} instead ({flex.savings_pct}% cheaper)
      </span>
    </button>
  );
}
