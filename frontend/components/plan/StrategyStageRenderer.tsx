/**
 * StrategyStageRenderer
 *
 * Main orchestrator for stage-aware right-side plan view.
 * Renders appropriate content based on current PlanViewState.
 *
 * State machine states:
 * - S0_BOOTSTRAP: Placeholders only
 * - S1_FRAMING: Skeleton structure
 * - S2_STRATEGY_READY: Strategy sections + open decisions
 * - S2_BLOCKED: Missing fields indicator
 * - S3_ITINERARY_READY: Day cards + overview
 * - S3_EDITING: Stale indicator + refresh CTA
 * - S3_BLOCKED: Gate failure indicator
 */

'use client';

import React from 'react';

import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import type {
  DestinationCard,
  PlanViewModel,
  PlanViewState,
} from '@/types/plan-envelope';

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
  /** Whether user can generate a plan (has destination + dates) */
  canGeneratePlan?: boolean;
  onExpandToItinerary?: () => void;
  onViewBookingOptions?: () => void;
  onReset?: () => void;
  onRefineAssumptions?: () => void;
}

export function StrategyStageRenderer({
  state,
  viewModel,
  destinationCard,
  canGeneratePlan = false,
  onExpandToItinerary,
  onViewBookingOptions,
  onReset: _onReset,
  onRefineAssumptions,
}: StrategyStageRendererProps) {
  // onReset reserved for future use (E_RESET event)
  void _onReset;
  // Enforce content policy in development
  React.useEffect(() => {
    guardedEnforcePolicy(state, viewModel);
  }, [state, viewModel]);

  // Render based on current state
  switch (state) {
    case 'S0_BOOTSTRAP':
      return <S0BootstrapView destinationCard={destinationCard} canGeneratePlan={canGeneratePlan} />;

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
          onExpandToItinerary={onExpandToItinerary}
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
          onViewBookingOptions={onViewBookingOptions}
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
      // Fallback to bootstrap view
      return <S0BootstrapView destinationCard={destinationCard} canGeneratePlan={canGeneratePlan} />;
  }
}

export default StrategyStageRenderer;
