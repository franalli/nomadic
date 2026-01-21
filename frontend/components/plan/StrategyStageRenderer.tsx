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
import type {
  DestinationCard,
  PlanViewModel,
  PlanViewState,
} from '@/types/plan-envelope';
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
  onExpandToItinerary?: () => void;
  onViewBookingOptions?: () => void;
  onReset?: () => void;
  onRefineAssumptions?: () => void;
  /** Last error from itinerary generation (for inline retry) */
  lastError?: string | null;
  /** Retry handler for itinerary generation */
  onRetry?: () => void;
}

function renderStageContent(
  state: PlanViewState,
  viewModel: PlanViewModel,
  destinationCard: DestinationCard | undefined,
  canGeneratePlan: boolean,
  onRefineAssumptions?: () => void,
  onExpandToItinerary?: () => void
): React.ReactNode {
  switch (state) {
    case 'S0_BOOTSTRAP':
      return (
        <S0BootstrapView
          destinationCard={destinationCard}
          canGeneratePlan={canGeneratePlan}
        />
      );

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
          viewModel={viewModel}
          destinationCard={destinationCard}
          onRefineAssumptions={onRefineAssumptions}
          canExpandToItinerary={viewModel.can_expand_to_itinerary ?? false}
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
      return (
        <S0BootstrapView
          destinationCard={destinationCard}
          canGeneratePlan={canGeneratePlan}
        />
      );
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
  onExpandToItinerary,
  onViewBookingOptions,
  onReset: _onReset,
  onRefineAssumptions,
  lastError,
  onRetry,
}: StrategyStageRendererProps) {
  // onReset reserved for future use (E_RESET event)
  void _onReset;

  // Enforce content policy in development
  React.useEffect(() => {
    guardedEnforcePolicy(state, viewModel);
  }, [state, viewModel]);

  const nextAction = getNextAction(state, generation);
  const currentStage = getStageFromState(state);
  const generating = isGenerating(generation);

  // Default fallback for unknown/empty states
  if (!state) {
    return (
      <div className="relative flex h-full flex-col overflow-hidden">
        <PlanHeader
          destinationCard={undefined}
          currentStage="bootstrap"
          fallbackTitle={fallbackTitle}
        />
        <div className="flex flex-1 items-center justify-center p-4">
          <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-6 text-center">
            <p className="text-sm text-zinc-500">
              Set destination and dates to begin
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      {/* Renderer owns header */}
      <PlanHeader
        destinationCard={destinationCard}
        currentStage={currentStage}
        isGenerating={generating}
        fallbackTitle={fallbackTitle}
      />

      {/* Stage content - scrollable with bottom padding for footer */}
      <div
        className={cn(
          'flex-1 overflow-y-auto',
          nextAction && 'pb-20' // Reserve space for sticky footer
        )}
      >
        {renderStageContent(
          state,
          viewModel,
          destinationCard,
          canGeneratePlan,
          onRefineAssumptions,
          onExpandToItinerary
        )}

        {/* BookingSection rendered conditionally (not "always") */}
        <BookingSection state={state} tiles={tiles} />
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
