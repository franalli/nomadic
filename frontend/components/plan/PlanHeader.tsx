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

import { AnimatePresence, motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import React from 'react';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { placeholderImagesForBranch } from '@/lib/placeholders';
import {
  getCompletedSteps,
  getStatusPillText,
  getStepIndex,
  getSubStatusText,
  STATUS_COPY,
} from '@/lib/statusCopyMap';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

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
  /** Trip inputs for displaying summary pills in S1+ */
  tripInputs?: DocumentTripInputs;
  /** Handler to open a sheet for editing trip inputs */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Whether streaming/generation is in progress (disables pills) */
  isStreaming?: boolean;
  /** Callback when Setup stage is clicked (navigate back to setup/config) */
  onSetupClick?: () => void;
  /** Callback when Plan stage is clicked (navigate to plan view) */
  onPlanClick?: () => void;
  /** Callback when Book stage is clicked (navigate to booking view) */
  onBookClick?: () => void;
  /** Whether user has minimum selections to enable Book stage */
  hasMinimumSelections?: boolean;
  /** Whether header is collapsed (mobile scroll state) */
  isCollapsed?: boolean;
}

/** Map step index to step key for callbacks */
const STEP_KEYS = ['setup', 'plan', 'book'] as const;
type StepKey = (typeof STEP_KEYS)[number];

/** Stage progress stepper - used in both variants */
function StageStepper({
  currentStepIndex,
  completedSteps,
  isGenerating,
  variant = 'default',
  onStepClick,
}: {
  currentStepIndex: number;
  completedSteps: boolean[];
  isGenerating: boolean;
  /** 'hero' for on-image, 'default' for placeholder/toolbar */
  variant?: 'default' | 'hero';
  /** Callback when a step is clicked (only for completed or active steps) */
  onStepClick?: (step: StepKey) => void;
}) {
  return (
    <div className="flex items-center gap-4">
      {STATUS_COPY.steps.map((label, idx) => {
        const isActive = idx === currentStepIndex;
        const isCompleted = completedSteps[idx] && !isActive;
        const isLocked = idx > currentStepIndex && !completedSteps[idx];
        const isCurrentGenerating = isActive && isGenerating;
        const isClickable = !isLocked && onStepClick;
        const stepKey = STEP_KEYS[idx];

        return (
          <button
            key={label}
            type="button"
            onClick={() => isClickable && onStepClick?.(stepKey)}
            disabled={isLocked || !onStepClick}
            className={cn(
              'flex items-center gap-1.5 text-xs transition-colors',
              // Color semantics: Amber=active, Green=completed, Gray=locked
              // Variant-aware: hero uses light text, default uses foreground
              isActive && (variant === 'hero' ? 'text-white font-medium' : 'text-foreground font-medium'),
              isCompleted && 'text-emerald-500 dark:text-emerald-400',
              isLocked && 'text-muted-foreground/70',
              // Clickable styles
              isClickable && !isActive && 'cursor-pointer hover:opacity-80',
              isClickable && isCompleted && 'hover:text-emerald-400',
              !isClickable && 'cursor-default'
            )}
          >
            {/* Progress dot */}
            <div
              className={cn(
                'h-1.5 w-1.5 rounded-full transition-colors',
                isActive && 'bg-amber-500 ring-2 ring-amber-500/30',
                isCompleted && 'bg-emerald-500',
                isLocked && 'bg-muted-foreground/30'
              )}
            />
            <span>{label}</span>
            {isCurrentGenerating && (
              <Loader2 className="h-3 w-3 animate-spin text-amber-500" />
            )}
          </button>
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
  tripInputs,
  onOpenSheet,
  isStreaming = false,
  onSetupClick,
  onPlanClick,
  onBookClick,
  hasMinimumSelections = false,
  isCollapsed = false,
}: PlanHeaderProps) {
  // currentStage kept for backwards compatibility but planViewState is preferred
  void _currentStage;
  // Determine variant based on whether we have a destination
  const title = destinationCard?.title || fallbackTitle || '';
  const hasDestination = Boolean(title);
  const subtitle = destinationCard?.subtitle;

  // Handle step clicks - map step key to appropriate callback
  const handleStepClick = React.useCallback(
    (step: StepKey) => {
      switch (step) {
        case 'setup':
          onSetupClick?.();
          break;
        case 'plan':
          onPlanClick?.();
          break;
        case 'book':
          // Only allow book click if minimum selections are met
          if (hasMinimumSelections) {
            onBookClick?.();
          }
          break;
      }
    },
    [onSetupClick, onPlanClick, onBookClick, hasMinimumSelections]
  );

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
      const placeholders = placeholderImagesForBranch({ destination: title });
      return placeholders[0] || '/assets/default-destination.jpg';
    }
    return null;
  }, [destinationCard?.image_url, title]);

  // Check if we should show pills (S1+ with tripInputs and handler)
  const showPills =
    planViewState !== 'S0_BOOTSTRAP' && tripInputs && onOpenSheet;

  // Format date range for collapsed view (must be before early return to maintain hook order)
  const startDate = tripInputs?.start_date;
  const endDate = tripInputs?.end_date;
  const dateRangeText = React.useMemo(() => {
    if (!startDate) return null;
    const start = new Date(startDate);
    const startFormatted = start.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
    if (endDate) {
      const end = new Date(endDate);
      const endFormatted = end.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
      });
      return `${startFormatted} - ${endFormatted}`;
    }
    return startFormatted;
  }, [startDate, endDate]);

  // PLACEHOLDER VARIANT: Compact bar when no destination
  // Uses secondary surface with visible border for light mode readability
  if (!hasDestination) {
    return (
      <div className="sticky top-0 z-10 flex-shrink-0 bg-secondary border-b border-border shadow-sm dark:bg-card/80 dark:backdrop-blur-md dark:border-border/60">
        <div className="max-w-[1100px] mx-auto w-full h-14 px-6 flex items-center justify-between">
          <StageStepper
            currentStepIndex={currentStepIndex}
            completedSteps={completedSteps}
            isGenerating={isGenerating}
            variant="default"
            onStepClick={handleStepClick}
          />
          {/* In S0: show CTA chip (desktop only - mobile uses SetupDrawer). In S1+: show pills if available */}
          {planViewState === 'S0_BOOTSTRAP' ? (
            <button
              type="button"
              onClick={() => onOpenSheet?.('destination')}
              className="hidden lg:inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors bg-amber-500/15 text-amber-900 border-amber-500/40 hover:bg-amber-500/25 dark:text-amber-300 dark:bg-amber-500/10 dark:hover:bg-amber-500/20"
            >
              Add destination + dates
            </button>
          ) : showPills ? (
            <TripSummaryPills
              tripInputs={tripInputs}
              onOpenSheet={onOpenSheet}
              disabled={isStreaming}
            />
          ) : (
            <span className="text-xs text-muted-foreground">Complete setup to continue</span>
          )}
        </div>
      </div>
    );
  }

  // HERO VARIANT: Full image header with destination (supports collapse)
  return (
    <div className="relative flex-shrink-0">
      {/* Hero image - collapsible on scroll */}
      <AnimatePresence>
        {!isCollapsed && (
          <motion.div
            className="relative h-40 overflow-hidden"
            initial={{ height: 160, opacity: 1 }}
            animate={{ height: 160, opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
          >
            {imageUrl ? (
              <img
                src={imageUrl}
                alt={title}
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              // Fallback gradient only if somehow no image (should not happen)
              <div className="absolute inset-0 bg-gradient-to-br from-secondary to-background" />
            )}

            {/* Scrim overlay for guaranteed text readability on any photo */}
            {/* Reduced darkness so image reads as intentional banner */}
            <div className="absolute inset-0 bg-gradient-to-r from-black/55 via-black/25 to-black/10" />
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/20 to-transparent" />

            {/* Content overlay */}
            <div className="absolute inset-0 flex flex-col justify-end p-4">
              <h2 className="text-xl font-semibold text-white">{title}</h2>
              {subtitle && (
                <p className="mt-0.5 text-sm text-white/85">{subtitle}</p>
              )}
              {/* Trip summary pills - only in S1+ (use onImage variant for hero) */}
              {showPills && (
                <div className="mt-3">
                  <TripSummaryPills
                    tripInputs={tripInputs}
                    onOpenSheet={onOpenSheet}
                    disabled={isStreaming}
                    variant="onImage"
                  />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Stage progress indicator with status pill */}
      <div className="border-b border-border bg-secondary dark:bg-card dark:border-border/60">
        <div className="flex items-center justify-between px-4 py-2">
          {/* Collapsed: show destination + date range instead of stepper */}
          {isCollapsed ? (
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-foreground">{title}</span>
              {dateRangeText && (
                <span className="text-xs text-muted-foreground">
                  ({dateRangeText})
                </span>
              )}
            </div>
          ) : (
            <StageStepper
              currentStepIndex={currentStepIndex}
              completedSteps={completedSteps}
              isGenerating={isGenerating}
              variant="default"
              onStepClick={handleStepClick}
            />
          )}

          {/* Status pill - shown during generation */}
          {statusPillText && (
            <div className="flex items-center gap-1.5 rounded-full bg-amber-500/15 px-2.5 py-1 text-xs text-amber-600 dark:text-amber-400 dark:bg-amber-500/10">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{statusPillText}</span>
            </div>
          )}
        </div>

        {/* Sub-status line - shown during generation (only when not collapsed) */}
        {subStatusText && !isCollapsed && (
          <div className="px-4 pb-2">
            <p className="text-xs text-muted-foreground">{subStatusText}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default PlanHeader;
