'use client';

import { Loader2 } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { BookingStatusItem } from '@/types/plan-envelope';

interface TabBookingStatusProps {
  status: BookingStatusItem | undefined | null;
  className?: string;
}

/**
 * TabBookingStatus - Per-tab booking status display.
 *
 * Shows factual status inside each tab:
 * - "Flights · 3 options found"
 * - "Stays · searching..."
 * - "Activities · not started"
 *
 * Rules:
 * - Short factual string
 * - No tone, no emoji
 * - Lives inside its tab, never global
 */
export const TabBookingStatus = memo(function TabBookingStatus({
  status,
  className,
}: TabBookingStatusProps) {
  if (!status) {
    return null;
  }

  const { state, summary } = status;

  return (
    <div
      className={cn(
        'flex items-center gap-2 text-xs text-muted-foreground',
        className
      )}
    >
      {/* Loading spinner for loading state */}
      {state === 'loading' && (
        <Loader2 className="h-3 w-3 animate-spin" />
      )}

      {/* Status dot for other states */}
      {state !== 'loading' && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full flex-shrink-0',
            state === 'ready' && 'bg-green-500',
            state === 'idle' && 'bg-muted-foreground/30',
            state === 'error' && 'bg-destructive'
          )}
        />
      )}

      {/* Summary text */}
      <span className={cn(state === 'error' && 'text-destructive/80')}>
        {summary}
      </span>
    </div>
  );
});
