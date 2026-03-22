'use client';

import { useMemo } from 'react';

import type { GenerationState } from '@/components/plan/planStateHelpers';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

export interface UsePlanViewContentArgs {
  planViewState: PlanViewState | null;
  planViewModel: PlanViewModel;
  destinationCard: DestinationCard | undefined;
  tiles: Record<string, Tile>;
  generation: GenerationState | null;
  canGeneratePlan: boolean;
  fallbackTitle: string | undefined;
  hasDates: boolean;
  isExpandingItinerary: boolean;
  handleBuildPlan: () => void;
  handleExpandToItinerary: () => Promise<void>;
  handleFinalizePlan: () => void;
  isFinalizing: boolean;
  preferredTileIds: Set<string>;
  handleSaveTilePreference: (tile: Tile) => void;
  tripInputs: DocumentTripInputs;
  isCommitting: boolean;
  openSheet: (name: SheetType) => void;
  hasEverHadPlan: boolean;
  isRegenerating: boolean;
  handleSelectNights: (nights: number) => void;
  handleOpenGearActivities: () => void;
  handleOpenGearStays: () => void;
  handleOpenGearFlights: () => void;
}

export function usePlanViewContent({
  planViewState,
  planViewModel,
  destinationCard,
  tiles,
  generation,
  canGeneratePlan,
  fallbackTitle,
  hasDates,
  isExpandingItinerary,
  handleBuildPlan,
  handleExpandToItinerary,
  handleFinalizePlan,
  isFinalizing,
  preferredTileIds,
  handleSaveTilePreference,
  tripInputs,
  isCommitting,
  openSheet,
  hasEverHadPlan,
  isRegenerating,
  handleSelectNights,
  handleOpenGearActivities,
  handleOpenGearStays,
  handleOpenGearFlights,
}: UsePlanViewContentArgs) {
  return useMemo(
    () => (
      <ErrorBoundary label="Plan View">
        <StrategyStageRenderer
          state={planViewState ?? 'P0_MINIMAL'}
          viewModel={planViewModel}
          destinationCard={destinationCard ?? undefined}
          tiles={tiles}
          generation={generation}
          canGeneratePlan={canGeneratePlan}
          fallbackTitle={fallbackTitle}
          hasDates={hasDates}
          isExpandingItinerary={isExpandingItinerary}
          onBuildPlan={handleBuildPlan}
          onExpandToItinerary={handleExpandToItinerary}
          onFinalizePlan={handleFinalizePlan}
          isFinalizing={isFinalizing}
          savedTileIds={preferredTileIds}
          onSaveTile={handleSaveTilePreference}
          tripInputs={tripInputs}
          isCommitting={isCommitting}
          onOpenSheet={openSheet}
          hasEverHadPlan={hasEverHadPlan}
          isRegenerating={isRegenerating}
          onSelectNights={handleSelectNights}
          onOpenActivitySettings={handleOpenGearActivities}
          onOpenStaysSettings={handleOpenGearStays}
          onOpenFlightsSettings={handleOpenGearFlights}
        />
      </ErrorBoundary>
    ),
    [
      canGeneratePlan,
      destinationCard,
      fallbackTitle,
      generation,
      handleBuildPlan,
      handleExpandToItinerary,
      handleFinalizePlan,
      handleOpenGearActivities,
      handleOpenGearFlights,
      handleOpenGearStays,
      handleSaveTilePreference,
      handleSelectNights,
      hasDates,
      hasEverHadPlan,
      isCommitting,
      isExpandingItinerary,
      isFinalizing,
      isRegenerating,
      openSheet,
      planViewModel,
      planViewState,
      preferredTileIds,
      tiles,
      tripInputs,
    ]
  );
}
