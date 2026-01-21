/**
 * PlanHeader
 *
 * Sticky header for the right-side plan panel.
 * Two variants:
 * 1. Empty (no destination) - Compact bar with stepper only
 * 2. Hero (destination exists) - Full image header with title/subtitle
 */

'use client';

import { Loader2 } from 'lucide-react';
import React from 'react';

import { placeholderImagesForBranch } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { DestinationCard } from '@/types/plan-envelope';

export interface PlanHeaderProps {
  destinationCard?: DestinationCard;
  currentStage: 'bootstrap' | 'structure' | 'strategy' | 'itinerary';
  isGenerating?: boolean;
  /** Fallback title from tripInputs if destinationCard not available */
  fallbackTitle?: string;
}

const STAGE_LABELS = ['Structure', 'Strategy', 'Itinerary'] as const;

function getStageIndex(stage: PlanHeaderProps['currentStage']): number {
  switch (stage) {
    case 'bootstrap':
      return -1;
    case 'structure':
      return 0;
    case 'strategy':
      return 1;
    case 'itinerary':
      return 2;
    default:
      return -1;
  }
}

/** Stage progress stepper - used in both variants */
function StageStepper({
  stageIndex,
  isGenerating,
  variant: _variant = 'default',
}: {
  stageIndex: number;
  isGenerating: boolean;
  variant?: 'default' | 'compact';
}) {
  return (
    <div className="flex items-center gap-4">
      {STAGE_LABELS.map((label, idx) => {
        const isActive = idx === stageIndex;
        const isCompleted = idx < stageIndex;
        const isLocked = idx > stageIndex;
        const isCurrentGenerating = isActive && isGenerating;

        return (
          <div
            key={label}
            className={cn(
              'flex items-center gap-1.5 text-xs transition-colors',
              // Enhanced visual emphasis per spec
              isActive && 'text-white font-medium',
              isCompleted && 'text-zinc-400',
              isLocked && 'text-zinc-600 opacity-60'
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
  currentStage,
  isGenerating = false,
  fallbackTitle,
}: PlanHeaderProps) {
  // Determine variant based on whether we have a destination
  const title = destinationCard?.title || fallbackTitle || '';
  const hasDestination = Boolean(title);
  const subtitle = destinationCard?.subtitle;
  const stageIndex = getStageIndex(currentStage);

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
      <div className="sticky top-0 z-10 flex-shrink-0 h-14 bg-black/30 backdrop-blur-md border-b border-zinc-800/60">
        <div className="max-w-[1100px] mx-auto w-full h-full px-6 flex items-center justify-between">
          <StageStepper stageIndex={stageIndex} isGenerating={isGenerating} variant="compact" />
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

      {/* Stage progress indicator */}
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4 py-2">
        <StageStepper stageIndex={stageIndex} isGenerating={isGenerating} />

        {/* Status indicator */}
        {isGenerating && (
          <span className="text-xs text-amber-500">
            Generating...
          </span>
        )}
      </div>
    </div>
  );
}

export default PlanHeader;
