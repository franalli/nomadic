'use client';

import type { ReactNode } from 'react';
import { useRef } from 'react';

import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';

import { BookingSummary } from './BookingSummary';
import { FullDensityTimeline } from './FullDensityTimeline';
import { OriginPromptCard } from './OriginPromptCard';
import { PlanFullDensityDesktopMap } from './PlanFullDensityDesktopMap';
import { PlanFullDensityMobileSummary } from './PlanFullDensityMobileSummary';
import { PlanFullDensityTilesSection } from './PlanFullDensityTilesSection';
import { PlanFullDensityTravelAdvice } from './PlanFullDensityTravelAdvice';
import type { PlanFullDensityViewProps } from './PlanFullDensityView.types';
import { isStrategyReady } from './planStateHelpers';
import { usePlanFullDensityData } from './usePlanFullDensityData';
import { useStickyHeaderOffset } from './useStickyHeaderOffset';

const DESKTOP_MAP_CONTENT_STYLE = { minWidth: 480, maxWidth: 800 } as const;

export function PlanFullDensityView({
  state,
  viewModel,
  fullModeSections,
  fullModePOIs,
  effectiveTiles,
  effectiveTripInputs,
  destinationCard,
  generation,
  savedTileIds,
  hasSectionData,
  hasItineraryContent,
  isExpandingItinerary,
  isStreaming,
  isAnyRegenerating,
  isRegenUpdating,
  isDesktop,
  preferenceCount,
  effectiveMode,
  timelineVariant,
  timelineSectionRef,
  scrollContainerRef,
  handleSaveTile,
  handleOpenBookingDrawer,
  onOpenStaysSettings,
  onOpenFlightsSettings,
  onOpenSheet: _onOpenSheet,
}: PlanFullDensityViewProps): ReactNode {
  const flexRowRef = useRef<HTMLDivElement>(null);
  const contentColRef = useRef<HTMLDivElement>(null);
  const headerOffset = useStickyHeaderOffset(scrollContainerRef);
  const {
    effectiveStrategySections,
    fullModeMapItems,
    mapCenter,
    showDesktopMap,
    destinationCenter,
    venueLinksActions,
    handleMarkerClick,
    stayCount,
    flightCount,
    staysExpanded,
    flightsExpanded,
    intelExpanded,
    onToggleStays,
    onToggleFlights,
    onToggleIntel,
    intelCategories,
    travelIntelItemCount,
    isTravelIntelPending,
    hasDestinationIntel,
    showTravelAdviceSegment,
  } = usePlanFullDensityData({
    viewModel,
    fullModeSections,
    fullModePOIs,
    effectiveTiles,
    effectiveTripInputs,
    destinationCard,
    isDesktop,
    isStreaming,
  });

  return (
    <div className="flex flex-col">
      <PlanFullDensityMobileSummary
        isDesktop={isDesktop}
        effectiveTripInputs={effectiveTripInputs}
        onOpenSheet={_onOpenSheet}
        isStreaming={isStreaming}
        hasItineraryContent={hasItineraryContent}
        flightCount={flightCount}
        stayCount={stayCount}
        travelIntelItemCount={travelIntelItemCount}
        showTravelAdviceSegment={showTravelAdviceSegment}
        isTravelIntelPending={isTravelIntelPending}
        flightsExpanded={flightsExpanded}
        staysExpanded={staysExpanded}
        intelExpanded={intelExpanded}
        onToggleFlights={onToggleFlights}
        onToggleStays={onToggleStays}
        onToggleIntel={onToggleIntel}
        dayCards={viewModel.day_cards}
      />

      <PlanFullDensityTravelAdvice
        hasDestinationIntel={hasDestinationIntel}
        intelExpanded={intelExpanded}
        intelCategories={intelCategories}
        isAnyRegenerating={isAnyRegenerating}
        isRegenUpdating={isRegenUpdating}
      />

      {isStrategyReady(state) &&
        effectiveTripInputs?.destination &&
        effectiveTripInputs?.start_date &&
        effectiveTripInputs?.end_date &&
        !effectiveTripInputs?.origin &&
        (viewModel.executed_strategy_topics?.length ?? 0) >= 2 && (
          <div className="mb-4 px-4">
            <OriginPromptCard
              onSetOrigin={(origin) => {
                useDocumentStore.getState().commitTripInputs({ origin });
              }}
            />
          </div>
        )}

      <PlanFullDensityTilesSection
        state={state}
        effectiveTiles={effectiveTiles}
        generation={generation}
        hasSectionData={hasSectionData}
        savedTileIds={savedTileIds}
        hasDates={!!effectiveTripInputs?.start_date}
        effectiveMode={effectiveMode as 'planning' | 'booking'}
        effectiveStrategySections={effectiveStrategySections}
        onOpenStaysSettings={onOpenStaysSettings}
        staysExpanded={staysExpanded}
        onToggleStays={onToggleStays}
        flightsExpanded={flightsExpanded}
        onToggleFlights={onToggleFlights}
        onSaveTile={handleSaveTile}
        isExpandingItinerary={isExpandingItinerary}
      />

      <div ref={flexRowRef} className={cn('flex', showDesktopMap && 'gap-6')}>
        <div
          ref={contentColRef}
          className={cn('flex min-w-0 flex-col', showDesktopMap ? 'flex-1' : 'w-full')}
          style={showDesktopMap ? DESKTOP_MAP_CONTENT_STYLE : undefined}
        >
          <FullDensityTimeline
            viewModel={viewModel}
            hasItineraryContent={hasItineraryContent}
            isExpandingItinerary={isExpandingItinerary}
            isStreaming={isStreaming}
            isRegenUpdating={isRegenUpdating}
            isDesktop={isDesktop}
            preferenceCount={preferenceCount}
            timelineVariant={timelineVariant}
            timelineSectionRef={timelineSectionRef}
            savedTileIds={savedTileIds}
            handleOpenBookingDrawer={handleOpenBookingDrawer}
            onOpenStaysSettings={onOpenStaysSettings}
            onOpenFlightsSettings={onOpenFlightsSettings}
            fullModeMapItems={fullModeMapItems}
            mapCenter={mapCenter}
            hasDestinationCenter={destinationCenter !== null}
            fullModePOIs={fullModePOIs}
          />
          <BookingSummary
            tiles={effectiveTiles}
            dayCards={viewModel.day_cards ?? []}
            state={state}
            headerActions={venueLinksActions}
          />
        </div>

        {showDesktopMap && (
          <PlanFullDensityDesktopMap
            headerOffset={headerOffset}
            fullModeMapItems={fullModeMapItems}
            mapCenter={mapCenter}
            onMarkerClick={handleMarkerClick}
          />
        )}
      </div>
    </div>
  );
}
