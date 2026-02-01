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

import { motion, AnimatePresence } from 'framer-motion';
import { useCallback, useEffect, useMemo, useRef } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { useScrollCollapse } from '@/hooks/useScrollCollapse';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import { getDestinationCoords } from '@/lib/destination-coords';
import {
  calculateMapCenter,
  extractPOIsFromSections,
  generateGhostDayCards,
  hasSpecialistContent,
} from '@/lib/ghost-timeline-adapter';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import {
  computePlanningPhase,
  computePlanningProgress,
  normalizePlanViewState,
  type DestinationCard,
  type PlanViewModel,
  type PlanViewState,
  type ViewMode,
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
  // Note: hasDateSet was removed from bridge mode condition per CRITICAL FIX comment below
  void tripInputs; // Silence unused parameter warning (kept for future use)

  // Normalize legacy S* values to P* values
  const normalizedState = normalizePlanViewState(state);

  // P0 with specialist content -> ghost (show draft timeline)
  if (normalizedState === 'P0_MINIMAL' && hasSpecialist) return 'ghost';

  // P0 without content -> empty (hero is the view)
  if (normalizedState === 'P0_MINIMAL') return 'empty';

  // P1 with specialist but no tiles -> bridge mode (shows strategy cards + ghost timeline)
  // CRITICAL FIX: Removed !hasDateSet condition - keep bridge mode until tiles are fetched
  // This ensures strategy cards remain visible in hero mode while waiting for tile fetch
  // (e.g., user said "diving in Bali" then "next week" but hasn't set origin)
  // @see docs/ux_unified_architecture.md Section VII - Bridge Mode
  if (normalizedState === 'P1_ENRICHED' && hasSpecialist && !hasTiles) return 'bridge';

  // Full mode: P1+ with tiles (booking options available) or P3 (finalized)
  return 'full';
}

import { Loader2 } from 'lucide-react';

import { BookingSection } from './BookingSection';
import { DestinationMapPlaceholder } from './DestinationMapPlaceholder';
import { NextStepBar } from './NextStepBar';
import { PlanHeader } from './PlanHeader';
import { SelectionsBar } from './SelectionsBar';
import {
  REVEAL_TIMING,
  SPRING_CONFIG,
} from '@/lib/animation-config';
import {
  type GenerationState,
  getNextAction,
  getStageFromState,
  isGenerating,
} from './planStateHelpers';
// Unified Planning View: Only S2StrategyView is used (specialist cards)
// Legacy stage views removed - timeline lives in Section 4, not embedded in stage content
// import { S1FramingView } from './stages/S1FramingView';
// import { S2BlockedView } from './stages/S2BlockedView';
import { S2StrategyView } from './stages/S2StrategyView';
// import { S3BlockedView } from './stages/S3BlockedView';
// import { S3EditingView } from './stages/S3EditingView';
// import { S3ItineraryView } from './stages/S3ItineraryView';
import { TimelineSkeleton } from './timeline/TimelineSkeleton';
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
  /** Two-mode system: explicit mode override (if not using view navigation) */
  mode?: ViewMode;
}

// renderStageContent - REMOVED for Unified Planning View
// In the unified single-scroll flow, we always use S2StrategyView for Section 1 (specialists)
// and TimelineThread for Section 4 (timeline). The old full-page views (S3ItineraryView, etc.)
// are no longer used in this architecture.
// @see docs/ux_unified_architecture.md - Unified Planning View

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
  mode: explicitMode,
}: StrategyStageRendererProps) {
  // onReset reserved for future use (E_RESET event)
  void _onReset;

  // FIX: Subscribe to store to catch updates even if parent doesn't re-render
  // Priority: Store (Live) > Props (Parent passed)
  const effectiveTripInputs = useTripInputsWithFallback(tripInputs);
  const storeTiles = useDocumentStore((s) => s.document?.tiles);
  const effectiveTiles = storeTiles ?? tiles;

  // Heart preference system for SelectionsBar
  const preferredTileIds = useDocumentStore((s) => s.preferredTileIds);
  const toggleTilePreference = useDocumentStore((s) => s.toggleTilePreference);

  // Get desktop state for mobile-specific rendering
  const { isDesktop } = useMobileMode();

  // Scroll collapse tracking for mobile header optimization
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isCollapsed = useScrollCollapse(scrollContainerRef, { threshold: 60, hysteresis: 15 });

  // Timeline ref for auto-scroll
  const timelineSectionRef = useRef<HTMLDivElement>(null);
  const prevHasItineraryRef = useRef(false);

  // Enforce content policy in development
  useEffect(() => {
    guardedEnforcePolicy(state, viewModel);
  }, [state, viewModel]);

  // Track hasItineraryContent for auto-scroll trigger
  const hasItineraryContent: boolean = state === 'S3_ITINERARY_READY' || state === 'S3_EDITING' ||
    Boolean(viewModel.day_cards && viewModel.day_cards.length > 0);

  // Auto-scroll to timeline when itinerary is generated
  useEffect(() => {
    // Only scroll when hasItineraryContent changes from false to true
    if (hasItineraryContent && !prevHasItineraryRef.current) {
      // Small delay to ensure DOM is rendered
      const timer = setTimeout(() => {
        timelineSectionRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      }, 300);
      return () => clearTimeout(timer);
    }
    prevHasItineraryRef.current = hasItineraryContent;
  }, [hasItineraryContent]);

  // hasTripContext = canGeneratePlan (destination + dates set)
  const nextAction = getNextAction(state, generation, canGeneratePlan);
  const currentStage = getStageFromState(state);
  const generating = isGenerating(generation);

  // Compute streaming state for disabling pills
  const isStreaming = generating || isCommitting || isExpandingItinerary;

  // View navigation - two-mode system (PLANNING + BOOKING)
  const { activeMode, canViewBooking, activeView, canViewSetup, canViewPlan, canViewBook: _canViewBook } = useViewNavigation();

  // Two-mode system: use activeMode from hook, allow explicit override
  const effectiveMode: ViewMode = explicitMode ?? activeMode;

  // Compute planning phase for ModeIndicator
  // Note: hasItineraryContent is computed above with auto-scroll logic
  const planningPhase = computePlanningPhase(
    effectiveTripInputs,
    hasItineraryContent,
    hasMinimumSelections
  );
  const planningProgress = computePlanningProgress(planningPhase);

  // =========================================================================
  // UNIFIED PLANNING VIEW - Preferences & Scroll State
  // =========================================================================

  // Scroll to a tile in the tiles section when clicked from SelectionsBar
  const scrollToTile = useCallback((tileId: string) => {
    const tileElement = document.querySelector(`[data-tile-id="${tileId}"]`);
    if (tileElement) {
      tileElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, []);

  // Plan content - heavy, needs persistence
  // Uses computeDataDensity for unified rendering logic
  // @see docs/ux_unified_architecture.md Section VII - Data Density Levels
  const planContent = useMemo(() => {
    // MIRROR LOADER: Show skeleton when auto-fetching tiles after dates are set
    // @see docs/ux_unified_architecture.md Section VI - "Mirror Loader Strategy"
    // Rule: "Never auto-switch to an empty container"
    const hasDates = !!effectiveTripInputs?.start_date;
    const hasTiles = effectiveTiles && Object.keys(effectiveTiles).length > 0;

    if (generating && hasDates && !hasTiles) {
      const tripDuration = effectiveTripInputs?.trip_duration ?? 3;
      return (
        <div className="p-4 space-y-6">
          {/* Status indicator */}
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
            <span className="text-sm text-muted-foreground">
              Searching live availability...
            </span>
          </div>

          {/* Timeline skeleton with days */}
          <TimelineSkeleton />

          {/* Duration hint */}
          <p className="text-xs text-muted-foreground text-center">
            Finding flights and hotels for your {tripDuration}-day trip
          </p>
        </div>
      );
    }

    // Compute data density using the SSoT function
    const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs);

    // EMPTY: S0 without specialist content - hero is the view
    if (density === 'empty') {
      return null;
    }

    // GHOST: S0 with specialist content - show "Planning Intelligence" panel + preview timeline
    // Cards are collapsed by default in SETUP mode - user can expand to see details
    // This ensures constraint visibility BEFORE date selection (core value prop)
    if (density === 'ghost') {
      const tripDuration = effectiveTripInputs?.trip_duration ?? 5;
      const ghostDayCards = generateGhostDayCards(viewModel.strategy_sections, tripDuration);
      const ghostHasDuration = !!effectiveTripInputs?.end_date || effectiveTripInputs?.trip_duration != null;

      // Count constraints across all specialists for the header badge
      const totalConstraints = (viewModel.strategy_sections ?? []).reduce(
        (acc, s) => acc + (s.constraints_applied?.length ?? 0),
        0
      );

      return (
        <div className="p-4 space-y-4">
          {/* PLANNING INTELLIGENCE HEADER */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                Planning Intelligence
              </h3>
            </div>
            {totalConstraints > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium">
                {totalConstraints} constraint{totalConstraints > 1 ? 's' : ''} applied
              </span>
            )}
          </div>

          {/* SPECIALIST CARDS (collapsed by default in SETUP mode) */}
          <S2StrategyView
            viewModel={viewModel}
            destinationCard={destinationCard}
            pendingTopics={viewModel.pending_strategy_topics}
            executedTopics={viewModel.executed_strategy_topics}
            tiles={{}} // No tiles in SETUP mode
            tripInputs={effectiveTripInputs}
            density="ghost"
            autoExpandOnLoad={false} // Cards stay collapsed in SETUP
          />

          {/* GHOST TIMELINE (preview of activities) */}
          <TimelineThread
            dayCards={ghostDayCards}
            isDraft={true}
            showPriceEstimates={false}
            hasDuration={ghostHasDuration}
            startDate={effectiveTripInputs?.start_date ?? null}
            onSelectNights={onSelectNights}
            onOpenDatePicker={() => onOpenSheet?.('dates')}
          />
          <div className="text-center pt-4 pb-8">
            <p className="text-sm text-muted-foreground">
              Activities from your specialists. Click &ldquo;Build Plan&rdquo; to see the full itinerary.
            </p>
          </div>
        </div>
      );
    }

    // BRIDGE: S2 with specialist but no tiles - Strategy Cards + POI Map
    // CRITICAL FIX: Removed ghost timeline - user wants NO ITINERARY in shopping phase
    // Show Strategy Cards (expert recommendations) + Map only
    // @see docs/ux_unified_architecture.md Section VII - Bridge Mode
    if (density === 'bridge') {
      const sections = viewModel.strategy_sections ?? [];
      const mapPOIs = extractPOIsFromSections(sections);

      // Get destination coordinates for map center
      const bridgeDestCoords = getDestinationCoords(destinationCard?.title);
      const bridgeMapCenter = bridgeDestCoords
        ? { lng: bridgeDestCoords[0], lat: bridgeDestCoords[1], zoom: 8 }
        : calculateMapCenter(mapPOIs);

      // Destination pin for the map (shown when no POIs available)
      const bridgeDestMarker: import('@/components/map/InteractiveMap').MapItem[] = bridgeDestCoords
        ? [{
            id: 'destination-pin',
            title: destinationCard?.title || 'Destination',
            type: 'destination',
            coordinates: { lat: bridgeDestCoords[1], lng: bridgeDestCoords[0] },
          }]
        : [];

      // Use POIs if available, otherwise show destination pin
      const bridgeMapItems = mapPOIs.length > 0 ? mapPOIs : bridgeDestMarker;

      // SETUP vs PLAN mode detection:
      // - No dates = SETUP mode = cards collapsed
      // - Has dates = PLAN mode = cards auto-expand briefly
      const hasDates = !!effectiveTripInputs?.start_date;

      // Count constraints for header badge
      const totalConstraints = sections.reduce(
        (acc, s) => acc + (s.constraints_applied?.length ?? 0),
        0
      );

      return (
        <div className="flex flex-col lg:flex-row gap-6 p-4">
          {/* Left Column: Strategy Cards Only (no timeline) */}
          <div className="flex-1 min-w-0 space-y-4">
            {/* PLANNING INTELLIGENCE HEADER (SETUP mode only - before dates) */}
            {!hasDates && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-lg">⚡</span>
                  <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                    Planning Intelligence
                  </h3>
                </div>
                {totalConstraints > 0 && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium">
                    {totalConstraints} constraint{totalConstraints > 1 ? 's' : ''} applied
                  </span>
                )}
              </div>
            )}

            {/* Strategy Cards - collapsed in SETUP (no dates), auto-expand in PLAN (has dates) */}
            <S2StrategyView
              viewModel={viewModel}
              destinationCard={destinationCard}
              pendingTopics={viewModel.pending_strategy_topics}
              executedTopics={viewModel.executed_strategy_topics}
              tiles={{}} // Empty - no booking tiles in bridge mode
              tripInputs={effectiveTripInputs}
              density="bridge"
              autoExpandOnLoad={hasDates} // SETUP = collapsed, PLAN = brief auto-expand
            />
          </div>

          {/* Right Column: Map (Fixed Width on Desktop) - shows destination pin or POIs */}
          <div className="hidden lg:block w-[350px] shrink-0">
            {/* Explicit height wrapper ensures Mapbox initializes correctly */}
            <div style={{ height: 400 }} className="rounded-xl overflow-hidden sticky top-4">
              {bridgeMapItems.length > 0 ? (
                <InteractiveMap
                  items={bridgeMapItems}
                  activeItemId={null}
                  defaultCenter={bridgeMapCenter}
                  className="h-full w-full"
                />
              ) : (
                <DestinationMapPlaceholder
                  destination={destinationCard?.title || 'Destination'}
                  imageUrl={destinationCard?.image_url || ''}
                  className="h-full"
                />
              )}
            </div>
          </div>
        </div>
      );
    }

    // Unified single-scroll view - no more subView toggle
    // Shows: Specialists → Tiles → Timeline (if generated)
    // Desktop P3+: 60/40 split with sticky map sidebar
    // Mobile: Inline map between tiles and timeline
    // @see docs/ux_unified_architecture.md - Unified Planning View

    // Get destination coordinates for map (used in P3+ only)
    const destCoords = getDestinationCoords(destinationCard?.title);
    const mapCenter = destCoords
      ? { lng: destCoords[0], lat: destCoords[1], zoom: 8 }
      : { lng: 0, lat: 0, zoom: 2 }; // Fallback world view

    // Desktop: Show sticky map sidebar when destination is set
    // Map appears immediately when destination is known, not just after itinerary
    const showDesktopMap = isDesktop && !!destCoords;

    // Destination pin for the map center
    const destinationMarker: import('@/components/map/InteractiveMap').MapItem[] = destCoords
      ? [{
          id: 'destination-pin',
          title: destinationCard?.title || 'Destination',
          type: 'destination',
          coordinates: { lat: destCoords[1], lng: destCoords[0] },
        }]
      : [];

    return (
      <div className={cn(
        'flex',
        // Desktop P3+: Content + fixed map layout
        showDesktopMap && 'gap-6'
      )}>
        {/* LEFT COLUMN: Main content (flex-1 on desktop P3+, 100% otherwise) */}
        <div
          className={cn(
            'flex flex-col min-w-0',
            showDesktopMap ? 'flex-1' : 'w-full'
          )}
          style={showDesktopMap ? { minWidth: 720, maxWidth: 900 } : undefined}
        >
          {/* SECTION 1: SPECIALISTS */}
          <section id="specialists-section" className="relative">
            <S2StrategyView
              key={`strategy-${destinationCard?.title}`}
              viewModel={viewModel}
              destinationCard={destinationCard}
              onRefineAssumptions={onRefineAssumptions}
              canExpandToItinerary={viewModel.can_expand_to_itinerary ?? false}
              pendingTopics={viewModel.pending_strategy_topics}
              executedTopics={viewModel.executed_strategy_topics}
              tiles={effectiveTiles}
              tripInputs={effectiveTripInputs}
              density={density}
            />

            {/* Regeneration overlay */}
            {isRegenerating && (
              <div className="absolute inset-0 z-10 flex items-start justify-center pt-20 bg-background/60 backdrop-blur-[1px]">
                <div className="flex flex-col items-center gap-3 rounded-lg bg-card/90 px-6 py-4 shadow-lg border border-border">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  <p className="text-sm font-medium text-muted-foreground">Updating plan...</p>
                </div>
              </div>
            )}
          </section>

          {/* SELECTIONS BAR - slides in when user has hearted tiles */}
          <AnimatePresence>
            {preferredTileIds.size > 0 && (
              <motion.div
                initial={{ y: -40, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: -40, opacity: 0 }}
                transition={{
                  type: 'spring',
                  stiffness: SPRING_CONFIG.SLIDE.stiffness,
                  damping: SPRING_CONFIG.SLIDE.damping,
                }}
                className={cn(
                  'sticky top-0 z-20',
                  isDesktop && 'mx-4'
                )}
              >
                <SelectionsBar
                  tiles={effectiveTiles}
                  preferredTileIds={preferredTileIds}
                  onRemovePreference={toggleTilePreference}
                  onTileClick={scrollToTile}
                  isSticky={isDesktop}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* SECTION 2: TILE BROWSER - fades in when tiles available */}
          <AnimatePresence>
            {effectiveTiles && Object.keys(effectiveTiles).length > 0 && (
              <motion.section
                key="tiles-section"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: REVEAL_TIMING.TILES_FADE / 1000 }}
                id="tiles-section"
                className={cn(
                  'mt-4 px-4',
                  isExpandingItinerary && 'opacity-60 pointer-events-none'
                )}
              >
                <BookingSection
                state={state}
                tiles={effectiveTiles}
                generation={generation}
                hasStrategyContent={(viewModel.strategy_sections?.length ?? 0) > 0}
                savedTileIds={savedTileIds}
                onSaveTile={onSaveTile}
                hasDates={!!effectiveTripInputs?.start_date}
                mode={effectiveMode}
                strategySections={viewModel.strategy_sections}
              />
              </motion.section>
            )}
          </AnimatePresence>

          {/* MOBILE ONLY: Inline map before timeline */}
          {!isDesktop && hasItineraryContent && (
            <section className="mt-4 px-4">
              {/* Explicit height wrapper ensures Mapbox initializes correctly */}
              <div style={{ height: 300 }} className="rounded-xl overflow-hidden border border-border/50">
                {destCoords ? (
                  <InteractiveMap
                    items={[]}
                    activeItemId={null}
                    defaultCenter={mapCenter}
                    className="h-full w-full"
                  />
                ) : (
                  <DestinationMapPlaceholder
                    destination={destinationCard?.title || 'Destination'}
                    imageUrl={destinationCard?.image_url || ''}
                    className="h-full"
                  />
                )}
              </div>
            </section>
          )}

          {/* SECTION 3: TIMELINE - fades in after generation */}
          <AnimatePresence>
            {hasItineraryContent && (
              <motion.section
                key="timeline-section"
                ref={timelineSectionRef}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: REVEAL_TIMING.TIMELINE_FADE / 1000 }}
                id="timeline-section"
                className="px-4 py-4"
              >
                <TimelineThread
                  dayCards={viewModel.day_cards ?? []}
                  variant="draft"
                  useRichBlocks={true}
                  savedTileIds={savedTileIds}
                />
              </motion.section>
            )}
          </AnimatePresence>

          {/* LOADING STATE: Show during itinerary generation */}
          {isExpandingItinerary && !hasItineraryContent && (
            <section className="flex flex-col items-center justify-center py-16 gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-emerald-500" />
              <span className="text-sm text-muted-foreground">Building your itinerary...</span>
            </section>
          )}
        </div>

        {/* RIGHT COLUMN: Sticky map - shows when destination is set (Desktop only, fixed 400px width) */}
        <AnimatePresence>
          {showDesktopMap && (
            <motion.div
              key="desktop-map"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3 }}
              className="shrink-0"
              style={{ width: 400, maxWidth: '35vw' }}
            >
              <div className="sticky top-20 z-10">
                {/* Explicit height wrapper ensures Mapbox initializes correctly */}
                <div style={{ height: 400 }} className="rounded-xl overflow-hidden border border-border/50">
                  <InteractiveMap
                    items={destinationMarker}
                    activeItemId={null}
                    defaultCenter={mapCenter}
                    className="h-full w-full"
                  />
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
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
    generating, // Added for Mirror Loader skeleton
    generation, // Added for BookingSection in Plan view
    savedTileIds,
    onSaveTile,
    effectiveMode, // Two-mode system
    hasItineraryContent,
    // Progressive disclosure dependencies
    preferredTileIds,
    toggleTilePreference,
    scrollToTile,
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
      hasDates={!!effectiveTripInputs?.start_date}
      mode="booking" // Book view is always in booking mode
      strategySections={viewModel.strategy_sections}
    />
  ), [state, effectiveTiles, generation, viewModel.strategy_sections, savedTileIds, onSaveTile, effectiveTripInputs?.start_date]);

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
          // Legacy props for GlassCommandBar fallback (deprecated)
          activeView={activeView}
          canViewSetup={canViewSetup}
          canViewPlan={canViewPlan}
          canViewBook={canViewBooking}
          // Two-mode system (PLANNING + BOOKING)
          useModeIndicator={true}
          mode={effectiveMode}
          planningPhase={planningPhase}
          progress={planningProgress}
        />

        {/* Content - direct render, scrollable */}
        <div
          ref={scrollContainerRef}
          className={cn(
            'flex-1 overflow-y-auto',
            nextAction && 'pb-32' // Space for MobilePlanFooter and sticky footer
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
        // Legacy props for GlassCommandBar fallback (deprecated)
        activeView={activeView}
        canViewSetup={canViewSetup}
        canViewPlan={canViewPlan}
        canViewBook={canViewBooking}
        // Two-mode system (PLANNING + BOOKING)
        useModeIndicator={true}
        mode={effectiveMode}
        planningPhase={planningPhase}
        progress={planningProgress}
      />

      {/* View container - relative positioning for absolute views */}
      <div className="flex-1 min-h-0 relative overflow-hidden">
        {/* VIEW: PLANNING - Two-mode system: PLANNING mode shows all planning content */}
        {/* Key-based rendering ensures clean unmount/remount, preventing ghosting */}
        {/* Trade-off: Map re-initializes on view switch (acceptable per plan) */}
        {effectiveMode === 'planning' && (
          <div
            key={`plan-${destinationCard?.title ?? 'default'}-${state}`}
            className="absolute inset-0 z-10 flex flex-col animate-in fade-in slide-in-from-left-4 duration-200"
          >
            {/* ISOLATED SCROLL CONTEXT - scrollbar lives HERE, not parent */}
            <div
              ref={scrollContainerRef}
              className={cn(
                'flex-1 overflow-y-auto custom-scrollbar min-h-0', // min-h-0 fixes flexbox content collapse on mobile
                nextAction && effectiveMode === 'planning' && 'pb-32' // Reserve space for sticky footer (button overlap fix)
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

        {/* VIEW: BOOKING (Absolute Overlay, unmounts) */}
        {effectiveMode === 'booking' && (
          <div className="absolute inset-0 z-20 animate-in fade-in slide-in-from-right-4 duration-200">
            <div className="h-full overflow-y-auto custom-scrollbar">
              {bookContent}
            </div>
          </div>
        )}
      </div>

      {/* Sticky footer - slides up, only shown in PLANNING mode, hidden on mobile */}
      <AnimatePresence>
        {nextAction && effectiveMode === 'planning' && (
          <motion.div
            key="next-step-bar"
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{
              type: 'spring',
              stiffness: SPRING_CONFIG.SLIDE.stiffness,
              damping: SPRING_CONFIG.SLIDE.damping,
            }}
            className="hidden lg:block"
          >
            <NextStepBar
              state={state}
              generation={generation}
              nextAction={nextAction}
              onExpandToItinerary={onExpandToItinerary}
              onOpenDates={() => onOpenSheet?.('dates')}
              lastError={lastError}
              onRetry={onRetry}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default StrategyStageRenderer;
