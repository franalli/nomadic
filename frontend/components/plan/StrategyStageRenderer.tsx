'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * StrategyStageRenderer — orchestrator for stage-aware right-side plan view.
 * Owns the chrome: header, scrollable body, sticky footer.
 * @see docs/ux_unified_architecture.md - Unified Planning View
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useMemo, useState } from 'react';

import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import {
  type DestinationCard,
  type PlanViewModel,
  type PlanViewState,
  type ViewMode,
} from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { BookingDrawer } from './booking/BookingDrawer';
import { BookingSection } from './BookingSection';
import { ItineraryProgressIndicator } from './ItineraryProgressIndicator';
import { NextStepBar } from './NextStepBar';
import {
  PlanBridgeDensityView,
  PlanGhostDensityView,
  PlanMirrorLoader,
} from './PlanDensityViews';
import { PlanFullDensityView } from './PlanFullDensityView';
import { PlanHeader } from './PlanHeader';
import { type GenerationState } from './planStateHelpers';
import { type TimelineVariant } from './TimelineThread';
import {
  computeDataDensity,
  type DataDensity,
  useStrategyStageOrchestration,
} from './useStrategyStageOrchestration';

export type { DataDensity };
export { computeDataDensity };

export function computeTimelineVariant(state: PlanViewState): TimelineVariant {
  if (state === 'S3_ITINERARY_READY') return 'real';
  if (state === 'S3_EDITING' || state === 'S2_STRATEGY_READY') return 'draft';
  return 'ghost';
}

interface StrategyStageRendererProps {
  state: PlanViewState;
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
  tiles?: Record<string, Tile>;
  generation?: GenerationState | null;
  canGeneratePlan?: boolean;
  fallbackTitle?: string;
  hasDates?: boolean;
  isExpandingItinerary?: boolean;
  onBuildPlan?: () => void;
  onExpandToItinerary?: () => Promise<void>;
  onFinalizePlan?: () => void;
  isFinalizing?: boolean;
  onRefineAssumptions?: () => void;
  savedTileIds?: Set<string>;
  onSaveTile?: (tile: Tile) => void;
  tripInputs?: DocumentTripInputs;
  onOpenSheet?: (sheet: SheetType) => void;
  isCommitting?: boolean;
  hasEverHadPlan?: boolean;
  isRegenerating?: boolean;
  onSelectNights?: (nights: number) => void;
  mode?: ViewMode;
  onOpenActivitySettings?: () => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
}

export function StrategyStageRenderer({
  state, viewModel, destinationCard, tiles = {}, generation,
  canGeneratePlan = false, fallbackTitle, hasDates = false,
  isExpandingItinerary = false, onBuildPlan: _onBuildPlan, onExpandToItinerary: _onExpand,
  onFinalizePlan: _onFinalize, isFinalizing: _isFinalizing = false, onRefineAssumptions,
  savedTileIds = new Set(), onSaveTile, tripInputs, onOpenSheet,
  isCommitting = false, hasEverHadPlan: _hasEverHadPlan = false,
  isRegenerating = false, onSelectNights, mode: explicitMode,
  onOpenActivitySettings, onOpenStaysSettings, onOpenFlightsSettings,
}: StrategyStageRendererProps) {
  const o = useStrategyStageOrchestration({
    state, viewModel, tiles, generation, canGeneratePlan, hasDates,
    isExpandingItinerary, isCommitting, isRegenerating, onSaveTile,
    tripInputs, mode: explicitMode, destinationTitle: destinationCard?.title,
  });

  const hasItinerary = state === 'S3_ITINERARY_READY' || state === 'S3_EDITING';

  const [staysExpanded, setStaysExpanded] = useState(!hasItinerary);
  const [flightsExpanded, setFlightsExpanded] = useState(false);
  const handleToggleStays = useCallback(() => setStaysExpanded(v => !v), []);
  const handleToggleFlights = useCallback(() => setFlightsExpanded(v => !v), []);

  const planContent = useMemo(() => {
    const { isShowingMirrorLoader, tripDuration } = o.displayLogic;
    const { fullModeSections, filteredViewModel, totalConstraints, ghostDayCards, ghostHasDuration } = o.specialistData;
    if (isShowingMirrorLoader) return <PlanMirrorLoader tripDuration={tripDuration} />;
    if (o.stableDensity === 'empty') return null;
    if (o.stableDensity === 'ghost') {
      return (
        <PlanGhostDensityView
          viewModel={viewModel} filteredViewModel={filteredViewModel}
          totalConstraints={totalConstraints} ghostDayCards={ghostDayCards}
          ghostHasDuration={ghostHasDuration} effectiveTripInputs={o.effectiveTripInputs}
          onSelectNights={onSelectNights} onOpenSheet={onOpenSheet}
          onOpenStaysSettings={onOpenStaysSettings} onOpenFlightsSettings={onOpenFlightsSettings}
          onOpenActivitySettings={onOpenActivitySettings}
        />
      );
    }
    if (o.stableDensity === 'bridge') {
      return (
        <PlanBridgeDensityView
          viewModel={viewModel} filteredViewModel={filteredViewModel}
          totalConstraints={totalConstraints} hasDates={o.displayLogic.hasDates}
          destinationCard={destinationCard} effectiveTripInputs={o.effectiveTripInputs}
          onOpenActivitySettings={onOpenActivitySettings}
        />
      );
    }
    return (
      <PlanFullDensityView
        state={state} viewModel={viewModel} filteredViewModel={filteredViewModel}
        fullModeSections={fullModeSections} fullModePOIs={o.fullModePOIs}
        effectiveTiles={o.effectiveTiles} effectiveTripInputs={o.effectiveTripInputs}
        destinationCard={destinationCard} generation={generation}
        savedTileIds={savedTileIds} hasSectionData={o.hasSectionData}
        hasItineraryContent={o.hasItineraryContent} isExpandingItinerary={isExpandingItinerary}
        isStreaming={o.isStreaming} isAnyRegenerating={o.isAnyRegenerating}
        isRegenUpdating={o.isRegenUpdating} isDesktop={o.isDesktop}
        showConstraints={o.showConstraints} preferenceCount={o.preferenceCount}
        effectiveMode={o.effectiveMode} timelineVariant={computeTimelineVariant(state)}
        timelineSectionRef={o.timelineSectionRef} scrollContainerRef={o.scrollContainerRef}
        onRefineAssumptions={onRefineAssumptions}
        handleSaveTile={o.handleSaveTile} handleOpenBookingDrawer={o.handleOpenBookingDrawer}
        onOpenActivitySettings={onOpenActivitySettings} onOpenStaysSettings={onOpenStaysSettings}
        onOpenFlightsSettings={onOpenFlightsSettings}
        onToggleConstraints={() => o.setShowConstraints(!o.showConstraints)}
        staysExpanded={staysExpanded} flightsExpanded={flightsExpanded}
        onToggleStays={handleToggleStays} onToggleFlights={handleToggleFlights}
      />
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- onOpenActivitySettings etc intentionally excluded
  }, [
    o.displayLogic, o.specialistData, o.stableDensity, o.effectiveTripInputs, o.fullModePOIs,
    o.effectiveTiles, o.hasSectionData, o.hasItineraryContent, o.isStreaming, o.isAnyRegenerating,
    o.isRegenUpdating, o.isDesktop, o.showConstraints, o.preferenceCount,
    o.effectiveMode, o.timelineSectionRef, o.scrollContainerRef, o.handleSaveTile, o.handleOpenBookingDrawer,
    state, viewModel, destinationCard, generation, savedTileIds, isExpandingItinerary,
    onRefineAssumptions, onSelectNights, onOpenSheet,
    staysExpanded, flightsExpanded, handleToggleStays, handleToggleFlights,
  ]);

  const bookContent = useMemo(() => (
    <BookingSection
      state={state} tiles={o.effectiveTiles} generation={generation}
      hasStrategyContent={o.hasSectionData} savedTileIds={savedTileIds}
      onSaveTile={o.handleSaveTile} hasDates={!!o.effectiveTripInputs?.start_date}
      mode="booking" strategySections={viewModel.strategy_sections}
      onOpenStaysSettings={onOpenStaysSettings}
    />
  ), [state, o.effectiveTiles, generation, viewModel.strategy_sections, o.hasSectionData, savedTileIds, o.handleSaveTile, o.effectiveTripInputs?.start_date, onOpenStaysSettings]);

  const drawer = (
    <BookingDrawer category={o.bookingDrawerCategory} tiles={o.effectiveTiles}
      savedTileIds={savedTileIds} onSave={o.handleSaveTile} onClose={o.handleCloseBookingDrawer}
      onOpenStaysSettings={onOpenStaysSettings} pinnedDayNumber={o.bookingDrawerPinnedDay} />
  );

  if (!o.isDesktop) {
    return (
      <>
        <div className="flex flex-col h-full">
          <div ref={o.scrollContainerRef} className={cn('flex-1 overflow-y-auto', o.nextAction && 'pb-32')}>
            <div className="relative min-h-full">
              <div className="pointer-events-none absolute inset-0 z-[1] bg-background/70 dark:bg-background/20" />
              <div className="relative z-[2]">{planContent}</div>
            </div>
          </div>
        </div>
        {drawer}
      </>
    );
  }

  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      <PlanHeader
        isGenerating={o.generating} fallbackTitle={fallbackTitle}
        planViewState={state} isExpandingItinerary={isExpandingItinerary}
        tripInputs={o.effectiveTripInputs} onOpenSheet={onOpenSheet} isStreaming={o.isStreaming}
        isCollapsed={!o.isDesktop && o.isCollapsed}
      />
      <div className="flex-1 min-h-0 relative overflow-hidden">
        {o.effectiveMode === 'planning' && (
          <div key={`plan-${destinationCard?.title ?? 'default'}-${state}`}
            className="absolute inset-0 z-10 flex flex-col animate-in fade-in slide-in-from-left-4 duration-200"
          >
            <div ref={o.scrollContainerRef} className={cn(
              'flex-1 overflow-y-auto custom-scrollbar min-h-0',
              o.nextAction && o.effectiveMode === 'planning' && 'pb-32'
            )}>
              <div className="relative">
                <div className="pointer-events-none absolute inset-0 z-[1] bg-background/70 dark:bg-background/20" />
                <div className="relative z-[2]">{planContent}</div>
              </div>
            </div>
          </div>
        )}
        {o.effectiveMode === 'booking' && (
          <div className="absolute inset-0 z-20 animate-in fade-in slide-in-from-right-4 duration-200">
            <div className="h-full overflow-y-auto custom-scrollbar">{bookContent}</div>
          </div>
        )}
      </div>
      <AnimatePresence mode="wait">
        {o.shouldShowAutoProgress && o.effectiveMode === 'planning' && (
          <motion.div key="progress-indicator"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className="sticky bottom-6 z-40 w-full justify-center pointer-events-none mt-8 hidden lg:flex"
          >
            <div className="pointer-events-auto w-fit mx-auto max-w-md">
              <ItineraryProgressIndicator
                stage={o.progressStage} specialists={viewModel.executed_strategy_topics ?? []}
                progress={generation?.pct} message={generation?.message}
              />
            </div>
          </motion.div>
        )}
        {o.nextAction && o.effectiveMode === 'planning' && !o.hideNextStepBar && (
          <motion.div key="next-step-bar"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className="hidden lg:block"
          >
            <NextStepBar state={state} nextAction={o.nextAction} />
          </motion.div>
        )}
      </AnimatePresence>
      {drawer}
    </div>
  );
}

export default StrategyStageRenderer;
