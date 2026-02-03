/**
 * NextStepBar
 *
 * "Command Island" - Sticky footer for finalizing the plan.
 * Uses sticky positioning to naturally respect the panel layout.
 * Place this at the bottom of your scrollable content area.
 *
 * NOTE: expand_itinerary action is now handled by RefreshButton FAB.
 * This component only handles finalize_plan action.
 */

'use client';

import { CheckCircle2, Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { PlanViewState } from '@/types/plan-envelope';

export interface NextStepBarProps {
  state: PlanViewState;
  /** Pre-computed next action from getNextAction() - avoids flicker */
  nextAction: 'expand_itinerary' | 'finalize_plan' | null;
  /** Callback to finalize plan and navigate to Book view */
  onFinalizePlan?: () => void;
  /** Whether plan finalization is in progress */
  isFinalizing?: boolean;
  className?: string;
}

export function NextStepBar({
  state,
  nextAction,
  onFinalizePlan,
  isFinalizing = false,
  className,
}: NextStepBarProps) {
  // Click lock to prevent double-clicks
  const [isClickLocked, setIsClickLocked] = useState(false);
  const clickLockTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup click lock timer on unmount
  useEffect(() => {
    return () => {
      if (clickLockTimerRef.current) {
        clearTimeout(clickLockTimerRef.current);
      }
    };
  }, []);

  // Read tripInputs from same store as chips - no prop drilling
  const tripInputs = useDocumentStore((state) => state.document?.trip_inputs);

  // Format date range for display (handles incomplete and single-day trips)
  const dateDisplay = (() => {
    if (!tripInputs?.start_date) return null;
    const start = new Date(tripInputs.start_date);
    const startStr = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    if (tripInputs.end_date) {
      const end = new Date(tripInputs.end_date);
      const isSameDay = start.toDateString() === end.toDateString();
      const days = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;

      if (isSameDay) {
        // Single day trip: show warning state
        return { range: startStr, days: 1, incomplete: true };
      }

      const endStr = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      return { range: `${startStr} — ${endStr}`, days, incomplete: false };
    }

    if (tripInputs.trip_duration) {
      return { range: startStr, days: tripInputs.trip_duration, incomplete: false };
    }

    // Start date only - show incomplete state with arrow
    return { range: `${startStr} → ?`, days: null, incomplete: true };
  })();

  // Reset click lock when finalization completes
  useEffect(() => {
    if (!isFinalizing) {
      setIsClickLocked(false);
    }
  }, [isFinalizing]);

  // Don't render if no action or if action is expand_itinerary (handled by RefreshButton FAB)
  if (state === 'S2_STRATEGY_READY' && !nextAction) {
    return null;
  }

  if (!nextAction) return null;

  // RefreshButton FAB handles expand_itinerary - NextStepBar only handles finalize_plan
  if (nextAction === 'expand_itinerary') {
    return null;
  }

  const handleClick = () => {
    if (isClickLocked) return;

    setIsClickLocked(true);
    onFinalizePlan?.();

    // Backup unlock after 2s (normally cleared by isFinalizing state change)
    if (clickLockTimerRef.current) {
      clearTimeout(clickLockTimerRef.current);
    }
    clickLockTimerRef.current = setTimeout(() => setIsClickLocked(false), 2000);
  };

  const buttonText = isFinalizing ? 'Scanning...' : 'Finalize & Book';
  const Icon = isFinalizing ? Loader2 : CheckCircle2;
  const isDisabled = isFinalizing || isClickLocked;
  const isActionReady = !isFinalizing;

  return (
    <div
      className={cn(
        // Sticky: Centers inside scroll container, respects panel layout
        'sticky bottom-6 z-40',
        'w-full flex justify-center',
        'pointer-events-none',
        'mt-8', // Space above the island
        className
      )}
    >
      {/* THE COMMAND ISLAND - w-fit forces shrink-wrap */}
      <div
        className={cn(
          'pointer-events-auto',
          'w-fit mx-auto', // KEY: w-fit snaps tight around content
          'flex items-center p-1.5',
          'rounded-full',
          // Material: Deep Glass
          'bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xl',
          'border border-zinc-200 dark:border-white/10',
          'shadow-2xl shadow-black/20 dark:shadow-black/50'
        )}
      >
        {/* LEFT: Context (Tight) */}
        <div className="px-4 flex flex-col justify-center">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-widest">
              Timeline
            </span>
            {dateDisplay?.days != null && dateDisplay.days >= 2 ? (
              <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-400/10 px-1.5 py-0.5 rounded">
                {dateDisplay.days} {dateDisplay.days === 1 ? 'day' : 'days'}
              </span>
            ) : dateDisplay?.incomplete ? (
              <span className="text-[10px] font-bold text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-400/10 px-1.5 py-0.5 rounded">
                needs dates
              </span>
            ) : null}
          </div>
          <div className={cn(
            'text-sm font-bold tracking-wide whitespace-nowrap mt-0.5',
            dateDisplay?.incomplete
              ? 'text-amber-600 dark:text-amber-400'
              : 'text-zinc-800 dark:text-white'
          )}>
            {dateDisplay?.range ?? 'Add dates'}
          </div>
        </div>

        {/* VERTICAL DIVIDER */}
        <div className="w-px h-8 bg-zinc-200 dark:bg-white/10 mx-2" />

        {/* RIGHT: Action Button */}
        <button
          onClick={handleClick}
          disabled={isDisabled}
          className={cn(
            'h-10 px-5 rounded-full',
            'flex items-center gap-2',
            'font-bold text-xs tracking-wide uppercase whitespace-nowrap',
            'transition-all duration-300',
            // Ready state: Green with localized glow
            isActionReady &&
              'bg-emerald-500 hover:bg-emerald-400 text-white shadow-[0_0_15px_-3px_rgba(16,185,129,0.4)] active:scale-95',
            // Processing state
            isFinalizing &&
              'bg-zinc-200 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 cursor-not-allowed'
          )}
        >
          <span>{buttonText}</span>
          <Icon
            className={cn(
              'w-3.5 h-3.5',
              isFinalizing && 'animate-spin',
              isActionReady && 'animate-pulse'
            )}
          />
        </button>
      </div>
    </div>
  );
}

export default NextStepBar;
