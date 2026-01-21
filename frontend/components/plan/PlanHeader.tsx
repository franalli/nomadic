/**
 * PlanHeader
 *
 * Sticky header for the right-side plan panel.
 * Two variants:
 * 1. Empty (no destination) - Compact bar with stepper only
 * 2. Hero (destination exists) - Full image header with title/subtitle
 *
 * Single progress system: Setup • Plan • Book
 * - Amber = active
 * - Green = completed only
 * - Gray = locked
 */

'use client';

import { Loader2 } from 'lucide-react';
import React from 'react';

import { placeholderImagesForBranch } from '@/lib/placeholders';
import {
  getCompletedSteps,
  getStepIndex,
  getStatusPillText,
  getSubStatusText,
  STATUS_COPY,
} from '@/lib/statusCopyMap';
import { cn } from '@/lib/utils';
import type { DestinationCard } from '@/types/plan-envelope';

export interface PlanHeaderProps {
  destinationCard?: DestinationCard;
  currentStage: 'bootstrap' | 'structure' | 'strategy' | 'itinerary';
  isGenerating?: boolean;
  /** Fallback title from tripInputs if destinationCard not available */
  fallbackTitle?: string;
  /** PlanViewState for accurate step tracking */
  planViewState?: string;
  /** Whether user has set dates */
  hasDates?: boolean;
  /** Whether expanding to itinerary (S3 generation) */
  isExpandingItinerary?: boolean;
  /** Current backend sub-stage (structure, strategy, itinerary, deals) */
  currentSubStage?: string | null;
}

/** Stage progress stepper - used in both variants */
function StageStepper({
  currentStepIndex,
  completedSteps,
  isGenerating,
}: {
  currentStepIndex: number;
  completedSteps: boolean[];
  isGenerating: boolean;
}) {
  return (
    <div className="flex items-center gap-4">
      {STATUS_COPY.steps.map((label, idx) => {
        const isActive = idx === currentStepIndex;
        const isCompleted = completedSteps[idx] && !isActive;
        const isLocked = idx > currentStepIndex && !completedSteps[idx];
        const isCurrentGenerating = isActive && isGenerating;

        return (
          <div
            key={label}
            className={cn(
              'flex items-center gap-1.5 text-xs transition-colors',
              // Color semantics: Amber=active, Green=completed, Gray=locked
              isActive && 'text-zinc-100 font-medium',
              isCompleted && 'text-emerald-400',
              isLocked && 'text-zinc-600/70'
            )}
          >
            {/* Progress dot */}
            <div
              className={cn(
                'h-1.5 w-1.5 rounded-full transition-colors',
                isActive && 'bg-amber-500',
                isCompleted && 'bg-emerald-500',
                isLocked && 'bg-zinc-700'
              )}
            />
            <span>{label}</span>
            {isCurrentGenerating && (
              <Loader2 className="h-3 w-3 animate-spin text-amber-500" />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function PlanHeader({
  destinationCard,
  currentStage: _currentStage,
  isGenerating = false,
  fallbackTitle,
  planViewState = 'S0_BOOTSTRAP',
  hasDates = false,
  isExpandingItinerary = false,
  currentSubStage,
}: PlanHeaderProps) {
  // currentStage kept for backwards compatibility but planViewState is preferred
  void _currentStage;
  // Determine variant based on whether we have a destination
  const title = destinationCard?.title || fallbackTitle || '';
  const hasDestination = Boolean(title);
  const subtitle = destinationCard?.subtitle;

  // Use statusCopyMap for accurate step tracking
  const currentStepIndex = getStepIndex(planViewState, hasDestination, hasDates);
  const completedSteps = getCompletedSteps(planViewState, hasDestination, hasDates);

  // Status pill and sub-status text
  const statusPillText = getStatusPillText(isGenerating, isExpandingItinerary);
  const subStatusText = isGenerating ? getSubStatusText(currentSubStage) : null;

  // Get image URL: always use placeholder if destination exists (never grey gradient)
  const imageUrl = React.useMemo(() => {
    if (destinationCard?.image_url) {
      return destinationCard.image_url;
    }
    // Always use placeholder for known destination - never fall back to grey
    if (title) {
      const placeholders = placeholderImagesForBranch({ destinations: [title] });
      return placeholders[0] || '/assets/default-destination.jpg';
    }
    return null;
  }, [destinationCard?.image_url, title]);

  // EMPTY VARIANT: Compact bar when no destination
  if (!hasDestination) {
    return (
      <div className="sticky top-0 z-10 flex-shrink-0 bg-black/30 backdrop-blur-md border-b border-zinc-800/60">
        <div className="max-w-[1100px] mx-auto w-full h-14 px-6 flex items-center justify-between">
          <StageStepper
            currentStepIndex={currentStepIndex}
            completedSteps={completedSteps}
            isGenerating={isGenerating}
          />
          <span className="text-xs text-zinc-500">Set destination + dates</span>
        </div>
      </div>
    );
  }

  // HERO VARIANT: Full image header with destination
  return (
    <div className="relative flex-shrink-0">
      {/* Hero image - always has image when destination exists */}
      <div className="relative h-32 overflow-hidden">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={title}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          // Fallback gradient only if somehow no image (should not happen)
          <div className="absolute inset-0 bg-gradient-to-br from-zinc-800 to-zinc-900" />
        )}

        {/* Dark overlay for text readability */}
        <div className="absolute inset-0 bg-gradient-to-t from-zinc-900/90 via-zinc-900/50 to-transparent" />

        {/* Content overlay */}
        <div className="absolute inset-0 flex flex-col justify-end p-4">
          <h2 className="text-xl font-semibold text-white">
            {title}
          </h2>
          {subtitle && (
            <p className="mt-0.5 text-sm text-zinc-300">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {/* Stage progress indicator with status pill */}
      <div className="border-b border-zinc-800 bg-zinc-900">
        <div className="flex items-center justify-between px-4 py-2">
          <StageStepper
            currentStepIndex={currentStepIndex}
            completedSteps={completedSteps}
            isGenerating={isGenerating}
          />

          {/* Status pill - shown during generation */}
          {statusPillText && (
            <div className="flex items-center gap-1.5 rounded-full bg-amber-500/10 px-2.5 py-1 text-xs text-amber-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{statusPillText}</span>
            </div>
          )}
        </div>

        {/* Sub-status line - shown during generation */}
        {subStatusText && (
          <div className="px-4 pb-2">
            <p className="text-xs text-zinc-500">{subStatusText}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default PlanHeader;
