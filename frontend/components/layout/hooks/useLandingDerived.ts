'use client';

/**
 * useLandingDerived
 *
 * Computes all derived values for NomadicLanding from store data and local state.
 * Pure useMemo computations - no side effects.
 */

import { useMemo } from 'react';

import type { GenerationState } from '@/components/plan/planStateHelpers';
import { isBootstrap } from '@/components/plan/planStateHelpers';
import { parseISODateLocal } from '@/lib/date-utils';
import { DEFAULT_TRIP_INPUTS } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type {
  DayCard,
  DestinationCard,
  ItineraryAssumptions,
  ItineraryOverview,
  OpenDecision,
  PlanState,
  PlanViewModel,
  PlanViewState,
  StrategySection,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface UseLandingDerivedParams {
  // Store values
  storeTripInputs: DocumentTripInputs | undefined;
  docPlanState: PlanState | undefined;
  docDestinationCard: DestinationCard | null | undefined;
  docPlanViewState: PlanViewState | undefined;
  docStrategySections: StrategySection[] | undefined;
  docTiles: Record<string, Tile> | undefined;
  docExecutedTopics: string[] | undefined;
  docPendingTopics: string[] | undefined;
  docDayCards: DayCard[] | undefined;
  docGeneration: GenerationState | undefined;
  docOpenDecisions: OpenDecision[] | undefined;
  docItineraryOverview: ItineraryOverview | null | undefined;
  docItineraryAssumptions: ItineraryAssumptions | null | undefined;
  docNeedsRefresh: boolean | undefined;
  docCanExpand: boolean | undefined;

  // Local state
  destinationImageUrl: string | null;
  isGenerating: boolean;
  hasEverHadPlan: boolean;
  userRequestedGeneration: boolean;
  uiGeneration: GenerationState | null;
  localPendingTopics: string[];
  hasBranchesReady: boolean;
}

export interface UseLandingDerivedResult {
  tripInputs: DocumentTripInputs;
  planState: PlanState;
  destinationCard: (DestinationCard & { image_url?: string }) | undefined;
  planViewState: PlanViewState;
  planViewModel: PlanViewModel;
  generation: GenerationState | null;
  tiles: Record<string, Tile>;
  planTabEnabled: boolean;
  canGeneratePlan: boolean;
  hasDates: boolean;
  hasPlan: boolean;
  fallbackTitle: string | undefined;
  hasOrigin: boolean;
  hasDestination: boolean;
  hasStartDate: boolean;
  hasEndDate: boolean;
  missingFields: string[];
  hasStrategyContent: boolean;
  hasTilesReady: boolean;
  hasDayCardsReady: boolean;
  docTileCount: number;
  mergedPendingTopics: string[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useLandingDerived({
  storeTripInputs,
  docPlanState,
  docDestinationCard,
  docPlanViewState,
  docStrategySections,
  docTiles,
  docExecutedTopics,
  docPendingTopics,
  docDayCards,
  docGeneration,
  docOpenDecisions,
  docItineraryOverview,
  docItineraryAssumptions,
  docNeedsRefresh,
  docCanExpand,
  destinationImageUrl,
  isGenerating,
  hasEverHadPlan,
  userRequestedGeneration,
  uiGeneration,
  localPendingTopics,
  hasBranchesReady,
}: UseLandingDerivedParams): UseLandingDerivedResult {
  // Derive tripInputs from store (with defaults)
  const tripInputs: DocumentTripInputs = useMemo(() => {
    if (!storeTripInputs) return DEFAULT_TRIP_INPUTS;
    return { ...DEFAULT_TRIP_INPUTS, ...storeTripInputs };
  }, [storeTripInputs]);

  const missingFields = tripInputs.missing_fields ?? [];

  // Check if we have origin or destination to show route
  const hasOrigin = Boolean(tripInputs.origin);
  const hasDestination = Boolean(tripInputs.destination);
  const hasStartDate = Boolean(tripInputs.start_date);
  const hasEndDate = Boolean(tripInputs.end_date);

  // Use backend-provided plan_state if available, otherwise derive from local state
  const documentPlanState = docPlanState;
  const planState: PlanState = useMemo(() => {
    if (documentPlanState) return documentPlanState;
    if (isGenerating) return 'RESOLVING';
    if (missingFields.length > 0 || !hasOrigin || !hasDestination || !hasStartDate) {
      return 'INCOMPLETE';
    }
    return 'STABLE';
  }, [
    documentPlanState,
    isGenerating,
    missingFields.length,
    hasOrigin,
    hasDestination,
    hasStartDate,
  ]);

  // Destination card (from backend or derive locally)
  const destinationCard = hasDestination
    ? {
        ...(docDestinationCard ?? {
          title: tripInputs.destination ?? '',
          subtitle: (() => {
            const parts: string[] = [];
            if (tripInputs.origin) {
              parts.push(`${tripInputs.origin} → ${tripInputs.destination ?? ''}`);
            }
            if (tripInputs.start_date) {
              const date = parseISODateLocal(tripInputs.start_date);
              if (date) {
                const formatted = date.toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                });
                parts.push(formatted);
              }
            }
            return parts.length > 0
              ? parts.join(' · ')
              : `Trip to ${tripInputs.destination ?? ''}`;
          })(),
        }),
        image_url: destinationImageUrl ?? docDestinationCard?.image_url ?? undefined,
      }
    : undefined;

  // Plan View State
  const backendPlanViewState = docPlanViewState;
  const hasStrategyContent = (docStrategySections?.length ?? 0) > 0;
  const docTileCount = useMemo(() => Object.keys(docTiles ?? {}).length, [docTiles]);
  const hasTilesReady = docTileCount > 0;
  const hasDayCardsReady = (docDayCards?.length ?? 0) > 0;

  const planViewState: PlanViewState = useMemo(() => {
    // Fast path: If plan content exists, trust backend's plan_view_state
    if (
      (hasTilesReady || hasDayCardsReady) &&
      backendPlanViewState &&
      backendPlanViewState !== 'S0_BOOTSTRAP'
    ) {
      return backendPlanViewState;
    }

    // Before user clicks "Build Plan", stay in Setup mode
    if (!hasEverHadPlan && !userRequestedGeneration && !hasTilesReady) {
      if (backendPlanViewState === 'S2_STRATEGY_READY' && hasStrategyContent) {
        return 'S2_STRATEGY_READY';
      }
      return 'S0_BOOTSTRAP';
    }

    // During generation, show loading state
    if (isGenerating && userRequestedGeneration) return 'S1_FRAMING';

    // CRITICAL: Check hasEverHadPlan BEFORE backend state
    if (hasEverHadPlan) {
      if (backendPlanViewState && backendPlanViewState !== 'S0_BOOTSTRAP') {
        return backendPlanViewState;
      }
      if (hasTilesReady) return 'S2_STRATEGY_READY';
      return hasStrategyContent ? 'S2_STRATEGY_READY' : 'S2_BLOCKED';
    }

    // User requested generation but plan not ready yet
    if (userRequestedGeneration) {
      if (backendPlanViewState && backendPlanViewState !== 'S0_BOOTSTRAP') {
        return backendPlanViewState;
      }
      return 'S1_FRAMING';
    }

    return 'S0_BOOTSTRAP';
  }, [
    backendPlanViewState,
    isGenerating,
    hasStrategyContent,
    hasEverHadPlan,
    userRequestedGeneration,
    hasTilesReady,
    hasDayCardsReady,
  ]);

  // Merge pending topics: backend + local optimistic
  const mergedPendingTopics = useMemo(() => {
    const backendPending = docPendingTopics ?? [];
    return Array.from(
      new Map([...backendPending, ...localPendingTopics].map((t) => [t, true])).keys()
    );
  }, [docPendingTopics, localPendingTopics]);

  // Plan View Model
  const planViewModel: PlanViewModel = useMemo(() => {
    return {
      strategy_sections: docStrategySections,
      executed_strategy_topics: docExecutedTopics,
      pending_strategy_topics: mergedPendingTopics,
      open_decisions: docOpenDecisions ?? [],
      itinerary_overview: docItineraryOverview ?? undefined,
      day_cards: docDayCards,
      itinerary_assumptions: docItineraryAssumptions ?? undefined,
      needs_refresh: docNeedsRefresh,
      can_expand_to_itinerary: docCanExpand,
    };
  }, [
    docStrategySections,
    docExecutedTopics,
    mergedPendingTopics,
    docOpenDecisions,
    docItineraryOverview,
    docDayCards,
    docItineraryAssumptions,
    docNeedsRefresh,
    docCanExpand,
  ]);

  // Merged generation state: envelope wins if present, else local UI fallback
  const envelopeGeneration = docGeneration as GenerationState | undefined;
  const generation: GenerationState | null = useMemo(() => {
    if (envelopeGeneration) return envelopeGeneration;
    if (uiGeneration) return uiGeneration;
    if (isGenerating) return { active: true, stage: 'structure' as const };
    return null;
  }, [envelopeGeneration, uiGeneration, isGenerating]);

  // Tiles from document store
  const tiles = useMemo(() => docTiles ?? {}, [docTiles]);

  // Plan tab enabled when we have branches/plan content
  const planTabEnabled = useMemo(() => {
    return hasBranchesReady || !isBootstrap(planViewState);
  }, [hasBranchesReady, planViewState]);

  // Fallback title
  const fallbackTitle = tripInputs.destination ?? undefined;

  // CTA gating flags
  const hasDates =
    (Boolean(tripInputs.start_date) && Boolean(tripInputs.end_date)) ||
    (tripInputs.date_flex === true && tripInputs.trip_duration != null);
  const canGeneratePlan = hasDestination && hasDates;
  const hasPlan = hasBranchesReady;

  return {
    tripInputs,
    planState,
    destinationCard,
    planViewState,
    planViewModel,
    generation,
    tiles,
    planTabEnabled,
    canGeneratePlan,
    hasDates,
    hasPlan,
    fallbackTitle,
    hasOrigin,
    hasDestination,
    hasStartDate,
    hasEndDate,
    missingFields,
    hasStrategyContent,
    hasTilesReady,
    hasDayCardsReady,
    docTileCount,
    mergedPendingTopics,
  };
}
