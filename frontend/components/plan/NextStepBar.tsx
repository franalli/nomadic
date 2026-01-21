/**
 * NextStepBar
 *
 * Sticky bottom CTA bar for the right-side plan panel.
 * Only renders when there's a meaningful next action.
 * Must be placed INSIDE the right-pane container, not global.
 */

'use client';

import React from 'react';
import { ArrowRight, Loader2, ShoppingBag } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { PlanViewState } from '@/types/plan-envelope';

import { getNextAction, type GenerationState } from './planStateHelpers';

export interface NextStepBarProps {
  state: PlanViewState;
  generation?: GenerationState | null;
  onExpandToItinerary?: () => void;
  onViewBookingOptions?: () => void;
  className?: string;
}

export function NextStepBar({
  state,
  generation,
  onExpandToItinerary,
  onViewBookingOptions,
  className,
}: NextStepBarProps) {
  const nextAction = getNextAction(state, generation);
  const isGeneratingItinerary = generation?.active && generation?.stage === 'itinerary';

  // Don't render if no action
  if (!nextAction) return null;

  const handleClick = () => {
    if (nextAction === 'expand_itinerary') {
      onExpandToItinerary?.();
    } else if (nextAction === 'view_booking') {
      onViewBookingOptions?.();
    }
  };

  const buttonConfig = {
    expand_itinerary: {
      label: isGeneratingItinerary ? 'Generating itinerary...' : 'Generate itinerary',
      icon: isGeneratingItinerary ? Loader2 : ArrowRight,
      disabled: isGeneratingItinerary,
      variant: 'primary' as const,
    },
    view_booking: {
      label: 'View booking options',
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
        'sticky bottom-0 left-0 right-0 border-t border-zinc-800 bg-zinc-900/95 p-4 backdrop-blur-sm',
        className
      )}
    >
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
        {config.label}
      </button>
    </div>
  );
}

export default NextStepBar;
