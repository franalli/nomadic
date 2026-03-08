'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * StrategyStageRenderer — orchestrator for stage-aware right-side plan view.
 * Owns the chrome: header, scrollable body, sticky footer.
 * @see docs/ux_unified_architecture.md - Unified Planning View
 */

import { AnimatePresence, motion } from 'framer-motion';
import { useMemo } from 'react';

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
import { PlanMirrorLoader } from './PlanDensityViews';
import { PlanFullDensityView } from './PlanFullDensityView';
import { PlanHeader } from './PlanHeader';
import { type GenerationState, isEditing, isItineraryReady, isStrategyReady } from './planStateHelpers';
import { type TimelineVariant } from './TimelineThread';
import {
  computeDataDensity,
  type DataDensity,
  useStrategyStageOrchestration,
} from './useStrategyStageOrchestration';

export type { DataDensity };
export { computeDataDensity };

export function computeTimelineVariant(state: PlanViewState): TimelineVariant {
  if (isItineraryReady(state)) return 'real';
  if (isEditing(state) || isStrategyReady(state)) return 'draft';
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

// Extracted animation constants to avoid re-creating objects on every render
const FADE_INITIAL = { opacity: 0 } as const;
const FADE_VISIBLE = { opacity: 1 } as const;
const FADE_EXIT = { opacity: 0 } as const;
const FADE_TRANSITION = { duration: 0.3, ease: [0.4, 0, 0.2, 1] } as const;

const EMPTY_SAVED_TILE_IDS = new Set<string>();

export function StrategyStageRenderer({
  state, viewModel, destinationCard, tiles = {}, generation,
  canGeneratePlan = false, fallbackTitle, hasDates = false,
  isExpandingItinerary = false, onBuildPlan: _onBuildPlan, onExpandToItinerary: _onExpand,
  onFinalizePlan: _onFinalize, isFinalizing: _isFinalizing = false, onRefineAssumptions,
  savedTileIds = EMPTY_SAVED_TILE_IDS, onSaveTile, tripInputs, onOpenSheet,
  isCommitting = false, hasEverHadPlan: _hasEverHadPlan = false,
  isRegenerating = false, onSelectNights: _onSelectNights, mode: explicitMode,
  onOpenActivitySettings: _onOpenActivitySettings, onOpenStaysSettings, onOpenFlightsSettings,
}: StrategyStageRendererProps) {
  const o = useStrategyStageOrchestration({
    state, viewModel, tiles, generation, canGeneratePlan, hasDates,
    isExpandingItinerary, isCommitting, isRegenerating, onSaveTile,
    tripInputs, mode: explicitMode, destinationTitle: destinationCard?.title,
  });

  const planContent = useMemo(() => {
    const { isShowingMirrorLoader, tripDuration, density: immediateDensity } = o.displayLogic;
    const { fullModeSections } = o.specialistData;
    if (isShowingMirrorLoader || immediateDensity === 'ghost') return <PlanMirrorLoader tripDuration={tripDuration} />;
    if (immediateDensity === 'empty' || immediateDensity === 'bridge') return null;
    return (
      <PlanFullDensityView
        state={state} viewModel={viewModel}
        fullModeSections={fullModeSections} fullModePOIs={o.fullModePOIs}
        effectiveTiles={o.effectiveTiles} effectiveTripInputs={o.effectiveTripInputs}
        destinationCard={destinationCard} generation={generation}
        savedTileIds={savedTileIds} hasSectionData={o.hasSectionData}
        hasItineraryContent={o.hasItineraryContent} isExpandingItinerary={isExpandingItinerary}
        isStreaming={o.isStreaming} isAnyRegenerating={o.isAnyRegenerating}
        isRegenUpdating={o.isRegenUpdating} isDesktop={o.isDesktop}
        preferenceCount={o.preferenceCount}
        effectiveMode={o.effectiveMode} timelineVariant={computeTimelineVariant(state)}
        timelineSectionRef={o.timelineSectionRef} scrollContainerRef={o.scrollContainerRef}
        handleSaveTile={o.handleSaveTile} handleOpenBookingDrawer={o.handleOpenBookingDrawer}
        onOpenStaysSettings={onOpenStaysSettings}
        onOpenFlightsSettings={onOpenFlightsSettings}
        onOpenSheet={onOpenSheet}
      />
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- onOpenActivitySettings etc intentionally excluded
  }, [
    o.displayLogic, o.specialistData, o.effectiveTripInputs, o.fullModePOIs,
    o.effectiveTiles, o.hasSectionData, o.hasItineraryContent, o.isStreaming, o.isAnyRegenerating,
    o.isRegenUpdating, o.isDesktop, o.preferenceCount,
    o.effectiveMode, o.timelineSectionRef, o.scrollContainerRef, o.handleSaveTile, o.handleOpenBookingDrawer,
    state, viewModel, destinationCard, generation, savedTileIds, isExpandingItinerary,
    onRefineAssumptions, onOpenSheet,
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
        tripInputs={o.effectiveTripInputs} dayCards={o.effectiveDayCards}
        onOpenSheet={onOpenSheet} isStreaming={o.isStreaming}
        isCollapsed={!o.isDesktop && o.isCollapsed}
      />
      <div className="flex-1 min-h-0 relative overflow-hidden">
        {o.effectiveMode === 'planning' && (
          <div key={`plan-${destinationCard?.title ?? 'default'}`}
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
            initial={FADE_INITIAL} animate={FADE_VISIBLE} exit={FADE_EXIT}
            transition={FADE_TRANSITION}
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
            initial={FADE_INITIAL} animate={FADE_VISIBLE} exit={FADE_EXIT}
            transition={FADE_TRANSITION}
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
