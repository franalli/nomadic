/**
 * NextStepBar
 *
 * "Command Island" - Sticky footer that centers inside the scroll container.
 * Uses sticky positioning to naturally respect the panel layout.
 * Place this at the bottom of your scrollable content area.
 */

'use client';

import { CheckCircle2, Loader2, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { useTripValidation } from '@/hooks/useTripValidation';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { PlanViewState } from '@/types/plan-envelope';

import type { GenerationState } from './planStateHelpers';

export interface NextStepBarProps {
  state: PlanViewState;
  generation?: GenerationState | null;
  /** Pre-computed next action from getNextAction() - avoids flicker */
  nextAction: 'expand_itinerary' | 'finalize_plan' | null;
  onExpandToItinerary?: () => void;
  /** Callback to finalize plan and navigate to Book view */
  onFinalizePlan?: () => void;
  /** Callback to open dates sheet when dates are missing */
  onOpenDates?: () => void;
  /** Whether plan finalization is in progress */
  isFinalizing?: boolean;
  /** Last error for inline retry (itinerary generation only) */
  lastError?: string | null;
  onRetry?: () => void;
  className?: string;
}

export function NextStepBar({
  state,
  generation,
  nextAction,
  onExpandToItinerary,
  onFinalizePlan,
  onOpenDates,
  isFinalizing = false,
  lastError,
  onRetry,
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

  // Unified validation state
  const validation = useTripValidation();

  const isGeneratingItinerary = generation?.active && generation?.stage === 'itinerary';

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

  // Reset click lock when generation completes
  useEffect(() => {
    if (!generation?.active) {
      setIsClickLocked(false);
    }
  }, [generation?.active]);

  // Don't render if no action
  if (state === 'S2_STRATEGY_READY' && !nextAction) {
    return null;
  }

  if (!nextAction) return null;

  // Validation-aware state (computed before handlers)
  const validationBlocked = nextAction === 'expand_itinerary' && !validation.valid;

  const handleClick = () => {
    if (isClickLocked) return;

    // If validation is blocked, open the dates sheet instead
    if (validationBlocked) {
      onOpenDates?.();
      return;
    }

    setIsClickLocked(true);

    if (nextAction === 'expand_itinerary') {
      onExpandToItinerary?.();
    } else if (nextAction === 'finalize_plan') {
      onFinalizePlan?.();
    }

    // Backup unlock after 2s (normally cleared by generation state change)
    if (clickLockTimerRef.current) {
      clearTimeout(clickLockTimerRef.current);
    }
    clickLockTimerRef.current = setTimeout(() => setIsClickLocked(false), 2000);
  };

  const buttonConfig = {
    expand_itinerary: {
      // Show validation action when blocked, otherwise normal flow
      buttonText: isGeneratingItinerary
        ? 'Building...'
        : validationBlocked
          ? validation.action
          : 'Build Itinerary',
      icon: isGeneratingItinerary ? Loader2 : Sparkles,
      // Disabled only when generating or click-locked (NOT when validation blocked - that's clickable)
      disabled: isGeneratingItinerary || isClickLocked,
    },
    finalize_plan: {
      buttonText: isFinalizing ? 'Scanning...' : 'Finalize & Book',
      icon: isFinalizing ? Loader2 : CheckCircle2,
      disabled: isFinalizing || isClickLocked,
    },
  };

  const config = buttonConfig[nextAction];
  const Icon = config.icon;
  // Action is ready when not generating, not finalizing, AND validation passes (for expand)
  const isActionReady = !isGeneratingItinerary && !isFinalizing && !validationBlocked;

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
          disabled={config.disabled}
          className={cn(
            'h-10 px-5 rounded-full',
            'flex items-center gap-2',
            'font-bold text-xs tracking-wide uppercase whitespace-nowrap',
            'transition-all duration-300',
            // Ready state: Green with localized glow
            isActionReady &&
              'bg-emerald-500 hover:bg-emerald-400 text-white shadow-[0_0_15px_-3px_rgba(16,185,129,0.4)] active:scale-95',
            // Validation blocked: Amber CTA - clickable to open dates
            validationBlocked &&
              'bg-amber-500 hover:bg-amber-400 text-white shadow-[0_0_15px_-3px_rgba(245,158,11,0.4)] active:scale-95 cursor-pointer',
            // Processing states
            (isGeneratingItinerary || isFinalizing) &&
              'bg-zinc-200 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 cursor-not-allowed'
          )}
        >
          <span>{config.buttonText}</span>
          <Icon
            className={cn(
              'w-3.5 h-3.5',
              (isGeneratingItinerary || isFinalizing) && 'animate-spin',
              isActionReady && 'animate-pulse'
            )}
          />
        </button>
      </div>

      {/* Error retry - floats below */}
      {nextAction === 'expand_itinerary' && lastError && (
        <div className="absolute top-full mt-2 left-0 right-0 flex justify-center pointer-events-auto">
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/10 border border-red-500/20">
            <span className="text-xs text-red-400">
              {(() => {
                // Parse structured error messages from backend
                try {
                  const parsed = JSON.parse(lastError);
                  if (parsed.error === 'MISSING_END_DATE') {
                    return 'Add return date to see itinerary';
                  }
                  if (parsed.error === 'TRIP_TOO_SHORT') {
                    return 'Trip must be at least 2 days';
                  }
                  if (parsed.error === 'CONSTRAINT_CONFLICT') {
                    return parsed.message || 'Activity constraints cannot fit in trip';
                  }
                  return parsed.message || lastError;
                } catch {
                  return lastError;
                }
              })()}
            </span>
            {onRetry && (
              <button
                onClick={onRetry}
                className="text-xs text-red-400 underline hover:text-red-300"
              >
                Retry
              </button>
            )}
          </div>
        </div>
      )}

    </div>
  );
}

export default NextStepBar;
