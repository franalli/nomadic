/**
 * PlanHeader
 *
 * Sticky header for the right-side plan panel.
 * Shows hero image with destination title/subtitle overlay and stage progress.
 */

'use client';

import React from 'react';
import { Loader2 } from 'lucide-react';

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

export function PlanHeader({
  destinationCard,
  currentStage,
  isGenerating = false,
  fallbackTitle,
}: PlanHeaderProps) {
  // Resolve image URL
  const title = destinationCard?.title || fallbackTitle || '';
  const subtitle = destinationCard?.subtitle;

  // Get image URL: use provided, then placeholder, then gradient fallback
  const imageUrl = React.useMemo(() => {
    if (destinationCard?.image_url) {
      return destinationCard.image_url;
    }
    if (title) {
      const placeholders = placeholderImagesForBranch({ destinations: [title] });
      return placeholders[0];
    }
    return null;
  }, [destinationCard?.image_url, title]);

  const stageIndex = getStageIndex(currentStage);

  return (
    <div className="relative flex-shrink-0">
      {/* Hero image or gradient fallback */}
      <div className="relative h-32 overflow-hidden">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={title || 'Destination'}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 bg-gradient-to-br from-zinc-800 to-zinc-900" />
        )}

        {/* Dark overlay for text readability */}
        <div className="absolute inset-0 bg-gradient-to-t from-zinc-900/90 via-zinc-900/50 to-transparent" />

        {/* Content overlay */}
        <div className="absolute inset-0 flex flex-col justify-end p-4">
          {title ? (
            <>
              <h2 className="text-xl font-semibold text-white">
                {title}
              </h2>
              {subtitle && (
                <p className="mt-0.5 text-sm text-zinc-300">
                  {subtitle}
                </p>
              )}
            </>
          ) : (
            <h2 className="text-lg text-zinc-400">
              Your plan
            </h2>
          )}
        </div>
      </div>

      {/* Stage progress indicator */}
      <div className="flex items-center justify-between border-b border-zinc-800 bg-zinc-900 px-4 py-2">
        <div className="flex items-center gap-4">
          {STAGE_LABELS.map((label, idx) => {
            const isActive = idx === stageIndex;
            const isCompleted = idx < stageIndex;
            const isCurrentGenerating = isActive && isGenerating;

            return (
              <div
                key={label}
                className={cn(
                  'flex items-center gap-1.5 text-xs transition-colors',
                  isActive && 'text-white',
                  isCompleted && 'text-zinc-500',
                  !isActive && !isCompleted && 'text-zinc-600'
                )}
              >
                {/* Progress dot */}
                <div
                  className={cn(
                    'h-1.5 w-1.5 rounded-full transition-colors',
                    isActive && 'bg-amber-500',
                    isCompleted && 'bg-zinc-500',
                    !isActive && !isCompleted && 'bg-zinc-700'
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
