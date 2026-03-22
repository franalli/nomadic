'use client';
/**
 * NextStepBar
 *
 * "Command Island" - Sticky footer for finalizing the plan.
 * Uses sticky positioning to naturally respect the panel layout.
 * Place this at the bottom of your scrollable content area.
 *
 * NOTE: expand_itinerary is handled via auto-expand in ChatPanel.
 * This component only handles finalize_plan action.
 */


import { CheckCircle2, Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { PlanViewState } from '@/types/plan-envelope';

import { formatDateDisplay } from './NextStepBarHelpers';
import { isStrategyReady } from './planStateHelpers';

interface NextStepBarProps {
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

  // Read only the date fields needed — avoids re-renders on unrelated trip_inputs changes
  const tripInputs = useDocumentStore(useShallow((state) => ({
    start_date: state.document?.trip_inputs?.start_date ?? null,
    end_date: state.document?.trip_inputs?.end_date ?? null,
    trip_duration: state.document?.trip_inputs?.trip_duration ?? null,
  })));

  const dateDisplay = formatDateDisplay(tripInputs);

  // Reset click lock when finalization completes
  useEffect(() => {
    if (!isFinalizing) {
      setIsClickLocked(false);
    }
  }, [isFinalizing]);

  // Don't render if no action or if action is expand_itinerary (handled by auto-expand)
  if (isStrategyReady(state) && !nextAction) {
    return null;
  }

  if (!nextAction) return null;

  // Auto-expand handles expand_itinerary - NextStepBar only handles finalize_plan
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
          'shadow-soft dark:shadow-black/50'
        )}
      >
        {/* LEFT: Context (Tight) */}
        <div className="px-4 flex flex-col justify-center">
          <div className="flex items-center gap-2">
            <span className={cn(DS.text.label, 'tracking-widest')}>
              Timeline
            </span>
            {dateDisplay?.pastDates ? (
              <span className={`${DS.textSize.micro} font-bold text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-400/10 px-1.5 py-0.5 rounded`}>
                past dates
              </span>
            ) : dateDisplay?.days != null && dateDisplay.days >= 2 ? (
              <span className={`${DS.textSize.micro} font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-400/10 px-1.5 py-0.5 rounded`}>
                {dateDisplay.days} {dateDisplay.days === 1 ? 'day' : 'days'}
              </span>
            ) : dateDisplay?.incomplete ? (
              <span className={`${DS.textSize.micro} font-bold text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-400/10 px-1.5 py-0.5 rounded`}>
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
              `bg-emerald-500 hover:bg-emerald-400 text-white ${DS.glowClass.action} active:scale-95`,
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
