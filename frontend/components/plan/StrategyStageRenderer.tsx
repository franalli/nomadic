/**
 * StrategyStageRenderer
 *
 * Main orchestrator for stage-aware right-side plan view.
 * Owns the chrome: header, scrollable body, sticky footer.
 * Stage views render content only.
 *
 * Layout:
 * ┌─────────────────────────────┐
 * │ PlanHeader (sticky top)     │  ← Renderer owns
 * ├─────────────────────────────┤
 * │ StageBody (scrollable)      │  ← Stage views render content here
 * │   - S0/S1/S2/S3 content     │
 * │   - BookingSection (S3)     │
 * ├─────────────────────────────┤
 * │ NextStepBar (sticky bottom) │  ← Renderer owns, gated by state
 * └─────────────────────────────┘
 */

'use client';

import React from 'react';

import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type {
  DestinationCard,
  PlanViewModel,
  PlanViewState,
} from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { BookingSection } from './BookingSection';
import { NextStepBar } from './NextStepBar';
import { PlanHeader } from './PlanHeader';
import {
  type GenerationState,
  getNextAction,
  getStageFromState,
  isGenerating,
} from './planStateHelpers';
import { S0BootstrapView } from './stages/S0BootstrapView';
import { S1FramingView } from './stages/S1FramingView';
import { S2BlockedView } from './stages/S2BlockedView';
import { S2StrategyView } from './stages/S2StrategyView';
import { S3BlockedView } from './stages/S3BlockedView';
import { S3EditingView } from './stages/S3EditingView';
import { S3ItineraryView } from './stages/S3ItineraryView';

interface StrategyStageRendererProps {
  state: PlanViewState;
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
  /** Tiles for BookingSection */
  tiles?: Record<string, Tile>;
  /** Generation state for gating */
  generation?: GenerationState | null;
  /** Whether user can generate a plan (has destination + dates) */
  canGeneratePlan?: boolean;
  /** Fallback title from tripInputs if no destinationCard */
  fallbackTitle?: string;
  /** Whether user has set dates (for stepper state) */
  hasDates?: boolean;
  /** Whether currently expanding to itinerary (S3 generation) */
  isExpandingItinerary?: boolean;
  /** Current backend sub-stage for status text */
  currentSubStage?: string | null;
  /** Handler to trigger plan generation from S0 "Build plan" CTA */
  onBuildPlan?: () => void;
  onExpandToItinerary?: () => void;
  onViewBookingOptions?: () => void;
  onReset?: () => void;
  onRefineAssumptions?: () => void;
  /** Last error from itinerary generation (for inline retry) */
  lastError?: string | null;
  /** Retry handler for itinerary generation */
  onRetry?: () => void;
  /** Shortlist: set of saved tile IDs */
  savedTileIds?: Set<string>;
  /** Shortlist: callback when user saves/unsaves a tile */
  onSaveTile?: (tile: Tile) => void;
  /** Trip inputs for displaying summary pills in header (S1+) */
  tripInputs?: DocumentTripInputs;
  /** Handler to open a sheet for editing trip inputs */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Whether committing/streaming is in progress (disables pills) */
  isCommitting?: boolean;
  /** Whether user has ever had a plan generated (for CTA label) */
  hasEverHadPlan?: boolean;
  /** Stage navigation: Setup click handler */
  onSetupClick?: () => void;
  /** Stage navigation: Plan click handler */
  onPlanClick?: () => void;
  /** Stage navigation: Book click handler */
  onBookClick?: () => void;
  /** Whether user has minimum selections to enable Book stage */
  hasMinimumSelections?: boolean;
}

function renderStageContent(
  state: PlanViewState,
  viewModel: PlanViewModel,
  destinationCard: DestinationCard | undefined,
  canGeneratePlan: boolean,
  onRefineAssumptions?: () => void,
  onExpandToItinerary?: () => void,
  onBuildPlan?: () => void,
  hasEverHadPlan?: boolean,
  tiles?: Record<string, Tile>
): React.ReactNode {
  // Note: S0BootstrapView now reads from document store directly
  // Action handlers for opening sheets will be added when we wire up the full chip row integration
  void canGeneratePlan; // Used to be passed to S0BootstrapView, now computed from store
  void destinationCard; // S0 no longer uses destination card (reads from store)

  switch (state) {
    case 'S0_BOOTSTRAP':
      return <S0BootstrapView onBuildPlan={onBuildPlan} hasEverHadPlan={hasEverHadPlan} />;

    case 'S1_FRAMING':
      return (
        <S1FramingView
          viewModel={viewModel}
          destinationCard={destinationCard}
        />
      );

    case 'S2_STRATEGY_READY':
      return (
        <S2StrategyView
          key={`strategy-${destinationCard?.destination}`}
          viewModel={viewModel}
          destinationCard={destinationCard}
          onRefineAssumptions={onRefineAssumptions}
          canExpandToItinerary={viewModel.can_expand_to_itinerary ?? false}
          pendingTopics={viewModel.pending_strategy_topics}
          executedTopics={viewModel.executed_strategy_topics}
          tiles={tiles}
        />
      );

    case 'S2_BLOCKED':
      return (
        <S2BlockedView
          viewModel={viewModel}
          destinationCard={destinationCard}
        />
      );

    case 'S3_ITINERARY_READY':
      return (
        <S3ItineraryView
          viewModel={viewModel}
          destinationCard={destinationCard}
        />
      );

    case 'S3_EDITING':
      return (
        <S3EditingView
          viewModel={viewModel}
          destinationCard={destinationCard}
          onRefresh={onExpandToItinerary}
        />
      );

    case 'S3_BLOCKED':
      return (
        <S3BlockedView
          viewModel={viewModel}
          destinationCard={destinationCard}
        />
      );

    default:
      return <S0BootstrapView onBuildPlan={onBuildPlan} hasEverHadPlan={hasEverHadPlan} />;
  }
}

export function StrategyStageRenderer({
  state,
  viewModel,
  destinationCard,
  tiles = {},
  generation,
  canGeneratePlan = false,
  fallbackTitle,
  hasDates = false,
  isExpandingItinerary = false,
  currentSubStage,
  onBuildPlan,
  onExpandToItinerary,
  onViewBookingOptions,
  onReset: _onReset,
  onRefineAssumptions,
  lastError,
  onRetry,
  savedTileIds = new Set(),
  onSaveTile,
  tripInputs,
  onOpenSheet,
  isCommitting = false,
  hasEverHadPlan = false,
  onSetupClick,
  onPlanClick,
  onBookClick,
  hasMinimumSelections = false,
}: StrategyStageRendererProps) {
  // onReset reserved for future use (E_RESET event)
  void _onReset;

  // Enforce content policy in development
  React.useEffect(() => {
    guardedEnforcePolicy(state, viewModel);
  }, [state, viewModel]);

  // hasTripContext = canGeneratePlan (destination + dates set)
  const nextAction = getNextAction(state, generation, canGeneratePlan);
  const currentStage = getStageFromState(state);
  const generating = isGenerating(generation);

  // Compute streaming state for disabling pills
  const isStreaming = generating || isCommitting || isExpandingItinerary;

  // Default fallback for unknown/empty states
  if (!state) {
    return (
      <div className="relative flex h-full flex-col overflow-hidden">
        <PlanHeader
          destinationCard={undefined}
          currentStage="bootstrap"
          fallbackTitle={fallbackTitle}
          planViewState="S0_BOOTSTRAP"
          hasDates={hasDates}
          tripInputs={tripInputs}
          onOpenSheet={onOpenSheet}
          isStreaming={isStreaming}
          onSetupClick={onSetupClick}
          onPlanClick={onPlanClick}
          onBookClick={onBookClick}
          hasMinimumSelections={hasMinimumSelections}
        />
        <div className="flex flex-1 items-center justify-center p-4">
          <div className="rounded-lg border border-border bg-card p-6 text-center shadow-sm">
            <p className="text-sm text-muted-foreground">
              Set destination and dates to begin
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      {/* Renderer owns header - single stepper + status pill + trip pills (S1+) */}
      <PlanHeader
        destinationCard={destinationCard}
        currentStage={currentStage}
        isGenerating={generating}
        fallbackTitle={fallbackTitle}
        planViewState={state}
        hasDates={hasDates}
        isExpandingItinerary={isExpandingItinerary}
        currentSubStage={currentSubStage}
        tripInputs={tripInputs}
        onOpenSheet={onOpenSheet}
        isStreaming={isStreaming}
        onSetupClick={onSetupClick}
        onPlanClick={onPlanClick}
        onBookClick={onBookClick}
        hasMinimumSelections={hasMinimumSelections}
      />

      {/* Stage content - scrollable with bottom padding for footer */}
      <div
        className={cn(
          'flex-1 overflow-y-auto',
          nextAction && 'pb-20' // Reserve space for sticky footer
        )}
      >
        {/* Content scrim - preserves topo visibility while ensuring content readability */}
        <div className="relative">
          {/* Scrim layer - stronger in light mode, subtle in dark */}
          <div className="pointer-events-none absolute inset-0 z-[1] bg-background/70 dark:bg-background/20" />
          {/* Content layer - above scrim */}
          <div className="relative z-[2]">
            {renderStageContent(
              state,
              viewModel,
              destinationCard,
              canGeneratePlan,
              onRefineAssumptions,
              onExpandToItinerary,
              onBuildPlan,
              hasEverHadPlan,
              tiles
            )}

            {/* BookingSection rendered conditionally (not "always") */}
            <BookingSection
              state={state}
              tiles={tiles}
              generation={generation}
              hasStrategyContent={(viewModel.strategy_sections?.length ?? 0) > 0}
              savedTileIds={savedTileIds}
              onSaveTile={onSaveTile}
            />
          </div>
        </div>
      </div>

      {/* Sticky footer - inside container, not global */}
      {nextAction && (
        <NextStepBar
          state={state}
          generation={generation}
          nextAction={nextAction}
          onExpandToItinerary={onExpandToItinerary}
          onViewBookingOptions={onViewBookingOptions}
          lastError={lastError}
          onRetry={onRetry}
        />
      )}
    </div>
  );
}

export default StrategyStageRenderer;
