'use client';

import { Check } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { ResolverStep } from '@/types/plan-envelope';
import { RESOLVER_STEPS, getResolverStepLabel } from '@/types/plan-envelope';

interface ResolverStackProps {
  activeStep: ResolverStep;
  completedSteps: Set<ResolverStep>;
  className?: string;
}

/**
 * ResolverStack - Linear textual progress indicator for RESOLVING state.
 *
 * Renders a fixed-order list of resolver steps:
 * • Processing constraints     (completed - checkmark)
 * • Matching inventory         (active - highlighted)
 * • Updating itinerary         (pending - dimmed)
 *
 * Rules:
 * - Exactly one active step (highlighted)
 * - Completed steps = muted + checkmark
 * - Future steps = dimmed
 * - Fixed order, no reordering, no branching
 * - Should only be visible when plan_state = "RESOLVING"
 */
export const ResolverStack = memo(function ResolverStack({
  activeStep,
  completedSteps,
  className,
}: ResolverStackProps) {
  return (
    <div
      className={cn(
        'rounded-md border border-primary/20 bg-primary/5 px-3 py-2',
        className
      )}
    >
      <ul className="space-y-1">
        {RESOLVER_STEPS.map((step) => {
          const isCompleted = completedSteps.has(step);
          const isActive = step === activeStep;
          const isPending = !isCompleted && !isActive;

          return (
            <li
              key={step}
              className={cn(
                'flex items-center gap-2 text-xs transition-colors',
                isActive && 'text-primary font-medium',
                isCompleted && 'text-muted-foreground',
                isPending && 'text-muted-foreground/50'
              )}
            >
              {/* Step indicator */}
              <span className="flex-shrink-0 w-4 flex items-center justify-center">
                {isCompleted ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : isActive ? (
                  <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
                ) : (
                  <span className="h-1 w-1 rounded-full bg-muted-foreground/30" />
                )}
              </span>

              {/* Step label */}
              <span>{getResolverStepLabel(step)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
});
