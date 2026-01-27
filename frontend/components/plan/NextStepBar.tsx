/**
 * NextStepBar
 *
 * Sticky bottom CTA bar for the right-side plan panel.
 * Only renders when there's a meaningful next action.
 * Must be placed INSIDE the right-pane container, not global.
 *
 * Key props:
 * - nextAction: Pre-computed from getNextAction() in parent to avoid flicker
 * - lastError + onRetry: Inline retry for itinerary generation errors
 */

'use client';

import { ArrowRight, Loader2, ShoppingBag } from 'lucide-react';
import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { PlanViewState } from '@/types/plan-envelope';

import type { GenerationState } from './planStateHelpers';

export interface NextStepBarProps {
  state: PlanViewState;
  generation?: GenerationState | null;
  /** Pre-computed next action from getNextAction() - avoids flicker */
  nextAction: 'expand_itinerary' | 'view_booking' | null;
  onExpandToItinerary?: () => void;
  onViewBookingOptions?: () => void;
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
  onViewBookingOptions,
  lastError,
  onRetry,
  className,
}: NextStepBarProps) {
  // Click lock to prevent double-clicks
  const [isClickLocked, setIsClickLocked] = useState(false);

  // Read tripInputs from same store as chips - no prop drilling
  const tripInputs = useDocumentStore((state) => state.document?.trip_inputs);

  const isGeneratingItinerary = generation?.active && generation?.stage === 'itinerary';

  // Check if duration is set (end_date OR trip_duration - no date_flex requirement)
  const hasDuration = !!tripInputs?.end_date || tripInputs?.trip_duration != null;
  const needsDuration = nextAction === 'expand_itinerary' && !hasDuration;

  // Reset click lock when generation completes
  useEffect(() => {
    if (!generation?.active) {
      setIsClickLocked(false);
    }
  }, [generation?.active]);

  // Show hint when S2_STRATEGY_READY but no nextAction (missing trip context)
  if (state === 'S2_STRATEGY_READY' && !nextAction) {
    return (
      <div
        className={cn(
          'sticky bottom-0 rounded-lg border border-border bg-card/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm shadow-lg',
          className
        )}
      >
        <p className="text-xs text-muted-foreground text-center">
          Create a plan first (destination + dates).
        </p>
      </div>
    );
  }

  // Don't render if no action
  if (!nextAction) return null;

  // Show hint when duration is missing - CTA still clickable to open TripLengthSheet
  if (needsDuration) {
    return (
      <div
        className={cn(
          'sticky bottom-0 rounded-lg border border-border bg-card/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm shadow-lg',
          className
        )}
      >
        <button
          onClick={onExpandToItinerary}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-600 text-white px-4 py-3 text-sm font-medium hover:bg-amber-500 transition-colors"
        >
          <ArrowRight className="h-4 w-4" />
          Create day-by-day itinerary
        </button>
        <p className="mt-2 text-center text-xs text-amber-600 dark:text-amber-400">
          Set trip length to create itinerary
        </p>
      </div>
    );
  }

  const handleClick = () => {
    if (isClickLocked) return;

    setIsClickLocked(true);

    if (nextAction === 'expand_itinerary') {
      onExpandToItinerary?.();
    } else if (nextAction === 'view_booking') {
      onViewBookingOptions?.();
    }

    // Backup unlock after 2s (normally cleared by generation state change)
    setTimeout(() => setIsClickLocked(false), 2000);
  };

  const buttonConfig = {
    expand_itinerary: {
      leftLabel: 'Next: Itinerary',
      buttonText: isGeneratingItinerary ? 'Creating itinerary...' : 'Create day-by-day itinerary',
      subtext: 'Unlocks a bookable plan (stays, flights, activities).',
      icon: isGeneratingItinerary ? Loader2 : ArrowRight,
      disabled: isGeneratingItinerary || isClickLocked,
      variant: 'primary' as const,
    },
    view_booking: {
      leftLabel: null,
      buttonText: 'View booking options',
      subtext: null,
      icon: ShoppingBag,
      disabled: false,
      variant: 'secondary' as const,
    },
  };

  const config = buttonConfig[nextAction];
  const Icon = config.icon;

  return (
    <div
      className={cn(
        'sticky bottom-0 rounded-lg border border-border bg-card/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm shadow-lg',
        className
      )}
    >
      {/* Left label for S2 */}
      {config.leftLabel && (
        <div className="text-xs text-muted-foreground mb-2">{config.leftLabel}</div>
      )}

      <button
        onClick={handleClick}
        disabled={config.disabled}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-sm font-medium transition-colors',
          config.variant === 'primary' && [
            'bg-amber-600 text-white',
            !config.disabled && 'hover:bg-amber-500',
            config.disabled && 'cursor-not-allowed opacity-70',
          ],
          config.variant === 'secondary' && [
            'bg-muted text-card-foreground',
            'hover:bg-muted/80',
          ]
        )}
      >
        <Icon className={cn('h-4 w-4', isGeneratingItinerary && 'animate-spin')} />
        {config.buttonText}
      </button>

      {/* Subtext for S2 */}
      {config.subtext && (
        <p className="text-xs text-muted-foreground mt-2 text-center">{config.subtext}</p>
      )}

      {/* Inline retry for itinerary generation errors only */}
      {nextAction === 'expand_itinerary' && lastError && (
        <div className="mt-2 flex items-center justify-center gap-2">
          <span className="text-xs text-red-400">{lastError}</span>
          {onRetry && (
            <button onClick={onRetry} className="text-xs text-amber-500 underline hover:text-amber-400">
              Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default NextStepBar;
