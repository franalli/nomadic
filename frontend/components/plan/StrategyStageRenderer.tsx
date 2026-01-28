/**
 * StrategyStageRenderer
 *
 * Main orchestrator for stage-aware right-side plan view.
 * Owns the chrome: header, scrollable body, sticky footer.
 * Stage views render content only.
 *
 * Zero-UI Architecture (S0_BOOTSTRAP):
 * - No form/checklist in center - controls live in sidebar (ChatPanel)
 * - Hero shows "Where to next?" with Living Topography
 * - Ghost timeline preview when specialist content available
 * - Setup view falls through to Plan view content (same visual)
 *
 * Layout:
 * ┌─────────────────────────────┐
 * │ PlanHeader (sticky top)     │  ← Hero + GlassCommandBar
 * ├─────────────────────────────┤
 * │ StageBody (scrollable)      │  ← Stage views render content here
 * │   - S0: Ghost timeline      │     (No form - Zero-UI)
 * │   - S1/S2/S3 content        │
 * ├─────────────────────────────┤
 * │ NextStepBar (sticky bottom) │  ← Renderer owns, gated by state
 * └─────────────────────────────┘
 */

'use client';

import React, { useMemo, useRef } from 'react';

import { useMobileMode } from '@/contexts/MobileModeContext';
import { useScrollCollapse } from '@/hooks/useScrollCollapse';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import { generateGhostDayCards, hasSpecialistContent } from '@/lib/ghost-timeline-adapter';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
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
// S0BootstrapView removed - Zero-UI: no form in center, controls live in sidebar
import { S1FramingView } from './stages/S1FramingView';
import { S2BlockedView } from './stages/S2BlockedView';
import { S2StrategyView } from './stages/S2StrategyView';
import { S3BlockedView } from './stages/S3BlockedView';
import { S3EditingView } from './stages/S3EditingView';
import { S3ItineraryView } from './stages/S3ItineraryView';
import { TimelineThread } from './TimelineThread';

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
  /** Callback to finalize plan and navigate to Book view */
  onFinalizePlan?: () => void;
  /** Whether finalization is in progress */
  isFinalizing?: boolean;
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
  /** Whether plan is currently regenerating due to constraint changes */
  isRegenerating?: boolean;
  /** Called when user selects a quick pick nights option from inline date prompt */
  onSelectNights?: (nights: number) => void;
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
  tiles?: Record<string, Tile>,
  isDesktop?: boolean,
  tripInputs?: DocumentTripInputs,
  onFinalizePlan?: () => void,
  isFinalizing?: boolean
): React.ReactNode {
  // Zero-UI: S0 controls live in sidebar, not center card
  // These params were for S0BootstrapView, now unused
  void canGeneratePlan;
  void onBuildPlan;
  void hasEverHadPlan;
  void isDesktop;

  switch (state) {
    case 'S0_BOOTSTRAP':
      // Zero-UI: No form in center - controls live in sidebar
      // This case shouldn't fire (planContent handles S0 specially) but defensive fallback
      return null;

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
          key={`strategy-${destinationCard?.title}`}
          viewModel={viewModel}
          destinationCard={destinationCard}
          onRefineAssumptions={onRefineAssumptions}
          canExpandToItinerary={viewModel.can_expand_to_itinerary ?? false}
          pendingTopics={viewModel.pending_strategy_topics}
          executedTopics={viewModel.executed_strategy_topics}
          tiles={tiles}
          tripInputs={tripInputs}
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
          onFinalize={onFinalizePlan}
          isFinalizing={isFinalizing}
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
      // Zero-UI: Unknown state fallback - show nothing, controls in sidebar
      return null;
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
  onFinalizePlan,
  isFinalizing = false,
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
  isRegenerating = false,
  onSelectNights,
}: StrategyStageRendererProps) {
  // onReset reserved for future use (E_RESET event)
  void _onReset;

  // FIX: Subscribe to store to catch updates even if parent doesn't re-render
  // Priority: Store (Live) > Props (Parent passed)
  const effectiveTripInputs = useTripInputsWithFallback(tripInputs);
  const storeTiles = useDocumentStore((s) => s.document?.tiles);
  const effectiveTiles = storeTiles ?? tiles;

  // Get desktop state for mobile-specific rendering
  const { isDesktop } = useMobileMode();

  // Scroll collapse tracking for mobile header optimization
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isCollapsed = useScrollCollapse(scrollContainerRef, { threshold: 60, hysteresis: 15 });

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

  // View navigation - decoupled from plan_view_state
  const { activeView, canViewSetup, canViewPlan, canViewBook } = useViewNavigation();

  // Setup content - Zero-UI: no form, just hero
  // The sidebar (ChatPanel) has all controls - no need for duplicate checklist
  const setupContent = useMemo(() => {
    // "Zero-UI" - the hero is the view, controls live in sidebar
    // Return null - the hero already shows "Where to next?" prompt
    return null;
  }, []);

  // Plan content - heavy, needs persistence
  // Guard: Show ghost timeline preview if S0_BOOTSTRAP with specialist content
  const planContent = useMemo(() => {
    if (state === 'S0_BOOTSTRAP') {
      // Check if we have specialist content for ghost timeline
      const hasContent = hasSpecialistContent(viewModel.strategy_sections);
      const tripDuration = effectiveTripInputs?.trip_duration ?? 5;

      if (hasContent) {
        // Generate ghost day cards from specialist content
        const ghostDayCards = generateGhostDayCards(viewModel.strategy_sections, tripDuration);
        // Check if we have duration set (for inline date prompt)
        const ghostHasDuration = !!effectiveTripInputs?.end_date || effectiveTripInputs?.trip_duration != null;

        return (
          <div className="p-4">
            <TimelineThread
              dayCards={ghostDayCards}
              isDraft={true}
              showPriceEstimates={false}
              // Inline date prompt props
              hasDuration={ghostHasDuration}
              startDate={effectiveTripInputs?.start_date ?? null}
              onSelectNights={onSelectNights}
              onOpenDatePicker={() => onOpenSheet?.('dates')}
            />
            {/* CTA hint at bottom */}
            <div className="text-center pt-4 pb-8">
              <p className="text-sm text-muted-foreground">
                Activities from your specialists. Click &ldquo;Build Plan&rdquo; to see the full itinerary.
              </p>
            </div>
          </div>
        );
      }

      // Zero-UI: No content in center for S0_BOOTSTRAP
      // Hero banner handles all messaging, center stays clean
      // Ghost timeline will appear here when specialist content is available
      return null;
    }
    return (
      <>
        {/* Stage content with regeneration overlay */}
        <div className="relative">
          {renderStageContent(
            state,
            viewModel,
            destinationCard,
            canGeneratePlan,
            onRefineAssumptions,
            onExpandToItinerary,
            onBuildPlan,
            hasEverHadPlan,
            effectiveTiles,
            isDesktop,
            effectiveTripInputs,
            onFinalizePlan,
            isFinalizing
          )}

          {/* Regeneration overlay - shows when constraints changed and plan is refreshing */}
          {isRegenerating && (
            <div className="absolute inset-0 z-10 flex items-start justify-center pt-20 bg-background/60 backdrop-blur-[1px]">
              <div className="flex flex-col items-center gap-3 rounded-lg bg-card/90 px-6 py-4 shadow-lg border border-border">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <p className="text-sm font-medium text-muted-foreground">Updating plan...</p>
              </div>
            </div>
          )}
        </div>
      </>
    );
  }, [
    state,
    viewModel,
    destinationCard,
    canGeneratePlan,
    onRefineAssumptions,
    onExpandToItinerary,
    onBuildPlan,
    hasEverHadPlan,
    effectiveTiles,
    isDesktop,
    effectiveTripInputs,
    isRegenerating,
    onFinalizePlan,
    isFinalizing,
    onSelectNights,
    onOpenSheet,
  ]);

  // Book content - full booking section view
  const bookContent = useMemo(() => (
    <BookingSection
      state={state}
      tiles={effectiveTiles}
      generation={generation}
      hasStrategyContent={(viewModel.strategy_sections?.length ?? 0) > 0}
      savedTileIds={savedTileIds}
      onSaveTile={onSaveTile}
    />
  ), [state, effectiveTiles, generation, viewModel.strategy_sections, savedTileIds, onSaveTile]);

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      {/* Header - always visible, controls view navigation */}
      <PlanHeader
        destinationCard={destinationCard}
        currentStage={currentStage}
        isGenerating={generating}
        fallbackTitle={fallbackTitle}
        planViewState={state}
        hasDates={hasDates}
        isExpandingItinerary={isExpandingItinerary}
        currentSubStage={currentSubStage}
        tripInputs={effectiveTripInputs}
        onOpenSheet={onOpenSheet}
        isStreaming={isStreaming}
        onSetupClick={onSetupClick}
        onPlanClick={onPlanClick}
        onBookClick={onBookClick}
        hasMinimumSelections={hasMinimumSelections}
        isCollapsed={!isDesktop && isCollapsed}
        activeView={activeView}
        canViewSetup={canViewSetup}
        canViewPlan={canViewPlan}
        canViewBook={canViewBook}
      />

      {/* View container - relative positioning for absolute views */}
      <div className="flex-1 relative overflow-hidden">
        {/* VIEW: SETUP - Zero-UI: No content overlay, just hero */}
        {/* The hero (PlanHeader) shows "Where to next?" - controls live in sidebar */}
        {/* When setupContent is null, we don't render an overlay - hero is the view */}
        {activeView === 'setup' && setupContent && (
          <div className="absolute inset-0 z-20 animate-in fade-in slide-in-from-left-4 duration-200">
            <div className="h-full overflow-y-auto custom-scrollbar p-4">
              {setupContent}
            </div>
          </div>
        )}

        {/* VIEW: PLAN (Persistent Layer - ALWAYS MOUNTED) */}
        {/* Uses opacity/pointer-events to preserve Scroll Position & Accordion State */}
        {/* Zero-UI: Also visible when Setup view has no content (controls in sidebar) */}
        <div
          className={cn(
            'absolute inset-0 flex flex-col transition-all duration-300',
            (activeView === 'plan' || (activeView === 'setup' && !setupContent))
              ? 'opacity-100 z-10 translate-x-0'
              : 'opacity-0 pointer-events-none z-0 -translate-x-4'
          )}
          aria-hidden={activeView !== 'plan' && !(activeView === 'setup' && !setupContent)}
        >
          {/* ISOLATED SCROLL CONTEXT - scrollbar lives HERE, not parent */}
          <div
            ref={scrollContainerRef}
            className={cn(
              'flex-1 overflow-y-auto custom-scrollbar',
              nextAction && activeView === 'plan' && 'pb-20' // Reserve space for sticky footer
            )}
          >
            {/* Content scrim - preserves topo visibility while ensuring content readability */}
            <div className="relative">
              {/* Scrim layer - stronger in light mode, subtle in dark */}
              <div className="pointer-events-none absolute inset-0 z-[1] bg-background/70 dark:bg-background/20" />
              {/* Content layer - above scrim */}
              <div className="relative z-[2]">{planContent}</div>
            </div>
          </div>
        </div>

        {/* VIEW: BOOK (Absolute Overlay, unmounts) */}
        {activeView === 'book' && (
          <div className="absolute inset-0 z-20 animate-in fade-in slide-in-from-right-4 duration-200">
            <div className="h-full overflow-y-auto custom-scrollbar">
              {bookContent}
            </div>
          </div>
        )}
      </div>

      {/* Sticky footer - only shown in Plan view, hidden on mobile (MobilePlanFooter handles mobile CTA) */}
      {nextAction && activeView === 'plan' && (
        <NextStepBar
          state={state}
          generation={generation}
          nextAction={nextAction}
          onExpandToItinerary={onExpandToItinerary}
          lastError={lastError}
          onRetry={onRetry}
          className="hidden lg:block"
        />
      )}
    </div>
  );
}

export default StrategyStageRenderer;
