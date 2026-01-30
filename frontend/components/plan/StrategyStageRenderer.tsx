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

import React, { useEffect, useMemo, useRef, useState } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { useScrollCollapse } from '@/hooks/useScrollCollapse';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import {
  calculateMapCenter,
  extractPOIsFromSections,
  generateGhostDayCards,
  hasSpecialistContent,
} from '@/lib/ghost-timeline-adapter';
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

// =============================================================================
// Data Density Computation (Grand Unification)
// =============================================================================

/**
 * Compute the current data density level for adaptive rendering.
 * This determines what content to show in the right panel.
 *
 * @see docs/ux_unified_architecture.md for the full specification
 */
export type DataDensity = 'empty' | 'ghost' | 'bridge' | 'full';

export function computeDataDensity(
  state: PlanViewState,
  strategySections: PlanViewModel['strategy_sections'],
  tiles: Record<string, Tile> | undefined,
  tripInputs: DocumentTripInputs | undefined
): DataDensity {
  const hasSpecialist = hasSpecialistContent(strategySections);
  const hasTiles = tiles && Object.keys(tiles).length > 0;
  const hasDateSet = !!tripInputs?.start_date;

  // S0 with specialist content -> ghost (show draft timeline)
  if (state === 'S0_BOOTSTRAP' && hasSpecialist) return 'ghost';

  // S0 without content -> empty (hero is the view)
  if (state === 'S0_BOOTSTRAP') return 'empty';

  // S2 with specialist but no tiles/dates -> bridge mode
  if (state === 'S2_STRATEGY_READY' && hasSpecialist && !hasTiles && !hasDateSet) return 'bridge';

  // Everything else -> full rendering
  return 'full';
}

import { BookingSection } from './BookingSection';
import { DestinationMapPlaceholder } from './DestinationMapPlaceholder';
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
  isFinalizing?: boolean,
  isExpandingItinerary?: boolean
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
          isGenerating={isExpandingItinerary}
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

  // Sub-view toggle: Overview (S2) vs Itinerary (S3) within Plan mode
  // Smart initialization: show itinerary if already generated, otherwise overview
  const [subView, setSubView] = useState<'overview' | 'itinerary'>(
    state === 'S3_ITINERARY_READY' ? 'itinerary' : 'overview'
  );

  // Auto-switch to itinerary when generation completes
  useEffect(() => {
    if (state === 'S3_ITINERARY_READY') {
      setSubView('itinerary');
    }
  }, [state]);

  // Check if itinerary has been generated (for showing toggle)
  const hasItinerary = state === 'S3_ITINERARY_READY' || state === 'S3_EDITING';

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

    // Bridge Mode Detection: S2 with specialist content but no tiles/dates
    // Shows Strategy Cards + Sample Day Flow + POI Map to inspire users before dates are set
    const hasTiles = effectiveTiles && Object.keys(effectiveTiles).length > 0;
    const hasDateSet = !!effectiveTripInputs?.start_date;
    const hasSpecialist = hasSpecialistContent(viewModel.strategy_sections);
    const isBridgeMode = state === 'S2_STRATEGY_READY' && hasSpecialist && !hasTiles && !hasDateSet;

    // DEBUG: Bridge Mode detection
    console.log('[BRIDGE MODE DEBUG]', {
      state,
      hasSpecialist,
      hasTiles,
      hasDateSet,
      isBridgeMode,
      strategySectionsCount: viewModel.strategy_sections?.length ?? 0,
      strategySectionTypes: viewModel.strategy_sections?.map(s => s.specialist_type) ?? [],
    });

    if (isBridgeMode) {
      // Bridge Mode: Strategy Cards + Ghost Timeline + POI Map
      const sections = viewModel.strategy_sections ?? [];

      // Calculate exact duration from content (don't default to 5)
      // Find the maximum day number from specialist content
      const maxContentDay = Math.max(
        0,
        ...sections.flatMap(s =>
          s.content_added?.map(c => c.day || 0) || []
        )
      );
      // Use trip_duration if set, otherwise fit to content (min 3 for diving safety sequence)
      const tripDuration = effectiveTripInputs?.trip_duration || (maxContentDay > 0 ? maxContentDay : 3);
      const ghostDayCards = generateGhostDayCards(sections, tripDuration);
      const mapPOIs = extractPOIsFromSections(sections);
      const mapCenter = calculateMapCenter(mapPOIs);

      // DEBUG: Log Bridge Mode data for verification
      console.log('[BRIDGE MODE CONTENT]', {
        tripDuration,
        ghostDayCardsCount: ghostDayCards.length,
        mapPOIsCount: mapPOIs.length,
        mapPOIs: mapPOIs.map(p => ({ title: p.title, coords: p.coordinates })),
        strategySections: viewModel.strategy_sections?.map(s => ({
          type: s.specialist_type,
          contentCount: s.content_added?.length ?? 0,
          hasCoordinates: s.content_added?.some(c => c.coordinates) ?? false,
        })),
      });

      return (
        <div className="flex flex-col lg:flex-row gap-6 p-4">
          {/* Left Column: Strategy + Timeline */}
          <div className="flex-1 min-w-0 space-y-6">
            {/* Strategy Cards */}
            <S2StrategyView
              viewModel={viewModel}
              destinationCard={destinationCard}
              pendingTopics={viewModel.pending_strategy_topics}
              executedTopics={viewModel.executed_strategy_topics}
              tiles={{}} // Empty - no booking tiles in bridge mode
              tripInputs={effectiveTripInputs}
            />

            {/* Sample Sequence (Ghost Timeline) - Clearly labeled as draft */}
            <div className="border-t border-border/50 pt-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-widest">
                  Sample Sequence (Draft)
                </h3>
                <span className="text-[10px] bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded text-zinc-500">
                  {tripDuration}-Day Logic Check
                </span>
              </div>
              <TimelineThread
                dayCards={ghostDayCards}
                isDraft={true}
                showPriceEstimates={false}
                hasDuration={false}
                startDate={null}
                onSelectNights={onSelectNights}
                onOpenDatePicker={() => onOpenSheet?.('dates')}
              />
            </div>
          </div>

          {/* Right Column: Map (Fixed Width on Desktop) */}
          <div className="hidden lg:block w-[350px] shrink-0">
            {mapPOIs.length > 0 ? (
              <InteractiveMap
                items={mapPOIs}
                activeItemId={null}
                defaultCenter={mapCenter}
                className="h-[400px] rounded-xl sticky top-4"
              />
            ) : (
              <DestinationMapPlaceholder
                destination={destinationCard?.title || 'Destination'}
                imageUrl={destinationCard?.image_url || ''}
                className="h-[400px] sticky top-4"
              />
            )}
          </div>
        </div>
      );
    }

    // Determine which view to show based on subView toggle
    // When in S3_ITINERARY_READY and subView is 'overview', show S2StrategyView
    const effectiveState = (hasItinerary && subView === 'overview')
      ? 'S2_STRATEGY_READY'
      : state;

    return (
      <>
        {/* Sub-view toggle - visible only after itinerary is generated */}
        {hasItinerary && (
          <div className="flex justify-center py-4 sticky top-0 z-30 bg-white/80 dark:bg-zinc-900/80 backdrop-blur-sm border-b border-zinc-200/50 dark:border-zinc-800/50">
            <div className="bg-zinc-200 dark:bg-zinc-800 p-1 rounded-full flex">
              <button
                onClick={() => setSubView('overview')}
                className={cn(
                  "px-6 py-2 rounded-full text-xs font-bold transition-all duration-200",
                  subView === 'overview'
                    ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-white"
                    : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                )}
              >
                Overview
              </button>
              <button
                onClick={() => setSubView('itinerary')}
                className={cn(
                  "px-6 py-2 rounded-full text-xs font-bold transition-all duration-200",
                  subView === 'itinerary'
                    ? "bg-white dark:bg-zinc-700 shadow-sm text-zinc-900 dark:text-white"
                    : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                )}
              >
                Itinerary
              </button>
            </div>
          </div>
        )}

        {/* Stage content with regeneration overlay */}
        <div className="relative">
          {renderStageContent(
            effectiveState,
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
            isFinalizing,
            isExpandingItinerary
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
    isExpandingItinerary,
    onSelectNights,
    onOpenSheet,
    hasItinerary,
    subView,
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

  // MOBILE: Simplified layout - no absolute positioning layer system
  // Desktop uses layers to preserve scroll position across view switches
  // Mobile uses SplitLayoutView tab switching instead
  if (!isDesktop) {
    return (
      <div className="flex flex-col h-full">
        {/* Header - always visible */}
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
          isCollapsed={isCollapsed}
          activeView={activeView}
          canViewSetup={canViewSetup}
          canViewPlan={canViewPlan}
          canViewBook={canViewBook}
        />

        {/* Content - direct render, scrollable */}
        <div
          ref={scrollContainerRef}
          className={cn(
            'flex-1 overflow-y-auto',
            nextAction && 'pb-24' // Space for MobilePlanFooter
          )}
        >
          {/* Content scrim for topo visibility */}
          <div className="relative min-h-full">
            <div className="pointer-events-none absolute inset-0 z-[1] bg-background/70 dark:bg-background/20" />
            <div className="relative z-[2]">{planContent}</div>
          </div>
        </div>
      </div>
    );
  }

  // DESKTOP: Layer system for view switching with scroll preservation
  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
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
      <div className="flex-1 min-h-0 relative overflow-hidden">
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

        {/* VIEW: PLAN (Conditional Rendering - Grand Unification) */}
        {/* Key-based rendering ensures clean unmount/remount, preventing ghosting */}
        {/* Trade-off: Map re-initializes on view switch (acceptable per plan) */}
        {/* Zero-UI: Also visible when Setup view has no content (controls in sidebar) */}
        {(activeView === 'plan' || (activeView === 'setup' && !setupContent)) && (
          <div
            key={`plan-${destinationCard?.title ?? 'default'}-${state}`}
            className="absolute inset-0 z-10 flex flex-col animate-in fade-in slide-in-from-left-4 duration-200"
          >
            {/* ISOLATED SCROLL CONTEXT - scrollbar lives HERE, not parent */}
            <div
              ref={scrollContainerRef}
              className={cn(
                'flex-1 overflow-y-auto custom-scrollbar min-h-0', // min-h-0 fixes flexbox content collapse on mobile
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
        )}

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
