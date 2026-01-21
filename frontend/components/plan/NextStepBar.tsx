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
import { useEffect,useState } from 'react';

import { cn } from '@/lib/utils';
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
  /** Count of saved stays (for gating CTA) */
  savedStaysCount?: number;
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
  savedStaysCount = 0,
  className,
}: NextStepBarProps) {
  // Click lock to prevent double-clicks
  const [isClickLocked, setIsClickLocked] = useState(false);

  const isGeneratingItinerary = generation?.active && generation?.stage === 'itinerary';

  // Shortlist gating: must have at least one saved stay to proceed to itinerary
  const needsStaySelection = nextAction === 'expand_itinerary' && savedStaysCount === 0;

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
          'sticky bottom-0 left-0 right-0 border-t border-zinc-800 bg-zinc-900/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm',
          className
        )}
      >
        <p className="text-xs text-zinc-500 text-center">
          Create a plan first (destination + dates).
        </p>
      </div>
    );
  }

  // Don't render if no action
  if (!nextAction) return null;

  // Show flow guide when user needs to save a stay first
  if (needsStaySelection) {
    return (
      <div
        className={cn(
          'sticky bottom-0 left-0 right-0 border-t border-zinc-800 bg-zinc-900/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm',
          className
        )}
      >
        {/* Flow indicator */}
        <div className="flex items-center justify-center gap-3 text-xs mb-3">
          <span className="flex items-center gap-1.5 text-amber-400">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500/20 text-[10px] font-medium">1</span>
            Save a stay
          </span>
          <span className="text-zinc-600">→</span>
          <span className="flex items-center gap-1.5 text-zinc-500">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-[10px] font-medium">2</span>
            Create itinerary
          </span>
          <span className="text-zinc-600">→</span>
          <span className="flex items-center gap-1.5 text-zinc-500">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-zinc-800 text-[10px] font-medium">3</span>
            Book
          </span>
        </div>

        {/* Disabled CTA with hint */}
        <button
          disabled
          className="flex w-full cursor-not-allowed items-center justify-center gap-2 rounded-lg bg-zinc-800 px-4 py-3 text-sm font-medium text-zinc-500 opacity-70"
        >
          <ArrowRight className="h-4 w-4" />
          Create day-by-day itinerary
        </button>
        <p className="mt-2 text-center text-xs text-zinc-500">
          Choose at least one stay to continue
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
        'sticky bottom-0 left-0 right-0 border-t border-zinc-800 bg-zinc-900/95 p-4 pb-[env(safe-area-inset-bottom)] backdrop-blur-sm',
        className
      )}
    >
      {/* Left label for S2 */}
      {config.leftLabel && (
        <div className="text-xs text-zinc-400 mb-2">{config.leftLabel}</div>
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
            'bg-zinc-800 text-zinc-200',
            'hover:bg-zinc-700',
          ]
        )}
      >
        <Icon className={cn('h-4 w-4', isGeneratingItinerary && 'animate-spin')} />
        {config.buttonText}
      </button>

      {/* Subtext for S2 */}
      {config.subtext && (
        <p className="text-xs text-zinc-500 mt-2 text-center">{config.subtext}</p>
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
