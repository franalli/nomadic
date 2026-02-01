/**
 * TimelineDivider
 *
 * Visual separator between tile browser and timeline section.
 * Shows generation status and provides context for timeline section.
 *
 * @see docs/ux_unified_architecture.md - Unified Planning View
 */

'use client';

import { Calendar, Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface TimelineDividerProps {
  /** Number of days in the itinerary */
  dayCount?: number;
  /** Trip date range display string */
  dateRange?: string;
  /** Whether timeline is currently being generated */
  isGenerating?: boolean;
  /** Additional className */
  className?: string;
}

export function TimelineDivider({
  dayCount,
  dateRange,
  isGenerating = false,
  className,
}: TimelineDividerProps) {
  return (
    <div className={cn('flex items-center gap-4 py-6', className)}>
      {/* Left line */}
      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-border to-border" />

      {/* Center badge */}
      <div
        className={cn(
          'flex items-center gap-2 px-4 py-2 rounded-full',
          'bg-zinc-800/60 border border-zinc-700/50',
          'text-xs font-medium text-zinc-300',
          isGenerating && 'animate-pulse'
        )}
      >
        {isGenerating ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-500" />
            <span>Building your itinerary...</span>
          </>
        ) : (
          <>
            <Calendar className="w-3.5 h-3.5 text-emerald-500" />
            <span className="uppercase tracking-wider">Your Itinerary</span>
            {dayCount && (
              <>
                <span className="text-zinc-500">•</span>
                <span className="text-zinc-400">
                  {dayCount} day{dayCount !== 1 ? 's' : ''}
                </span>
              </>
            )}
            {dateRange && (
              <>
                <span className="text-zinc-500">•</span>
                <span className="text-zinc-500">{dateRange}</span>
              </>
            )}
          </>
        )}
      </div>

      {/* Right line */}
      <div className="flex-1 h-px bg-gradient-to-l from-transparent via-border to-border" />
    </div>
  );
}

export default TimelineDivider;
