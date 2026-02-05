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
 * │ PlanHeader (sticky top)     │  ← Hero + StatusBadge
 * ├─────────────────────────────┤
 * │ StageBody (scrollable)      │  ← Stage views render content here
 * │   - S0: Ghost timeline      │     (No form - Zero-UI)
 * │   - S1/S2/S3 content        │
 * ├─────────────────────────────┤
 * │ NextStepBar (sticky bottom) │  ← Renderer owns, gated by state
 * └─────────────────────────────┘
 */

'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Shield } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useToast } from '@/components/ui/toast';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { useScrollCollapse } from '@/hooks/useScrollCollapse';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import { getDestinationCoords } from '@/lib/destination-coords';
import {
  calculateMapCenter,
  extractPOIsFromDayCards,
  extractPOIsFromSections,
  generateGhostDayCards,
  hasSpecialistContent,
} from '@/lib/ghost-timeline-adapter';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import {
  type DestinationCard,
  normalizePlanViewState,
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

import {
  REVEAL_TIMING,
  SPRING_CONFIG,
} from '@/lib/animation-config';

import { BookingSection } from './BookingSection';
import { type ConflictData, type ConflictResolution,ConflictResolutionBanner } from './ConflictResolutionBanner';
import { DestinationMapPlaceholder } from './DestinationMapPlaceholder';
import { ItineraryProgressIndicator, type ProgressStage } from './ItineraryProgressIndicator';
import { NextStepBar } from './NextStepBar';
// Unified Planning View: Only S2StrategyView is used (specialist cards)
// Legacy stage views removed - timeline lives in Section 4, not embedded in stage content
// import { S1FramingView } from './stages/S1FramingView';
// import { S2BlockedView } from './stages/S2BlockedView';
import { OriginPromptCard } from './OriginPromptCard';
import { PlanHeader } from './PlanHeader';
import {
  type GenerationState,
  getNextAction,
  getStageFromState,
  isGenerating,
  isMultiSpecialistTrip,
} from './planStateHelpers';
import { ReadyToPlanBanner } from './ReadyToPlanBanner';
import { S2StrategyView } from './stages/S2StrategyView';
// import { S3BlockedView } from './stages/S3BlockedView';
// import { S3EditingView } from './stages/S3EditingView';
// import { S3ItineraryView } from './stages/S3ItineraryView';
import { TimelineSkeleton } from './timeline/TimelineSkeleton';
import { TimelineThread, type TimelineVariant } from './TimelineThread';

/**
 * Compute timeline variant based on current planning state.
 * - S3_ITINERARY_READY: 'real' (finalized itinerary - no badge)
 * - S3_EDITING/S2_STRATEGY_READY: 'draft' (work in progress)
 * - Others: 'ghost' (preview)
 * @see docs/ux_unified_architecture.md
 */
function computeTimelineVariant(state: PlanViewState): TimelineVariant {
  if (state === 'S3_ITINERARY_READY') return 'real';
  if (state === 'S3_EDITING' || state === 'S2_STRATEGY_READY') return 'draft';
  return 'ghost';
}

/**
 * Get alternative destination suggestions for infeasible specialists
 */
function getAlternativeDestinations(specialistType?: string): string {
  switch (specialistType?.toLowerCase()) {
    case 'diving':
      return 'Consider Bali, Red Sea, or Maldives.';
    case 'skiing':
      return 'Consider Alps, Aspen, or Hokkaido.';
    case 'hiking':
      return 'Consider Nepal, Patagonia, or Swiss Alps.';
    case 'surfing':
      return 'Consider Bali, Hawaii, or Portugal.';
    case 'boating':
      return 'Consider Greece, Croatia, or Caribbean.';
    default:
      return 'Try a different destination.';
  }
}

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
  onExpandToItinerary?: () => Promise<void>;
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
  /** Whether plan is currently regenerating due to constraint changes */
  isRegenerating?: boolean;
  /** Called when user selects a quick pick nights option from inline date prompt */
  onSelectNights?: (nights: number) => void;
  /** Two-mode system: explicit mode override (if not using view navigation) */
  mode?: ViewMode;
  /** Conflict data from ItineraryBuilder (Path A) */
  conflictData?: ConflictData | null;
  /** Callback when user selects a conflict resolution */
  onResolveConflict?: (resolution: ConflictResolution) => void;
  /** Callback to open activity settings sheet (for specialist gear icons) */
  onOpenActivitySettings?: () => void;
  /** Callback to open stays/hotel settings sheet (for hotel gear icons) */
  onOpenStaysSettings?: () => void;
  /** Callback to open flights settings sheet (for flight gear icons) */
  onOpenFlightsSettings?: () => void;
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
  lastError: _lastError,
  onRetry: _onRetry,
  savedTileIds = new Set(),
  onSaveTile,
  tripInputs,
  onOpenSheet,
  isCommitting = false,
  hasEverHadPlan = false,
  isRegenerating = false,
  onSelectNights,
  mode: explicitMode,
  conflictData,
  onResolveConflict,
  onOpenActivitySettings,
  onOpenStaysSettings,
  onOpenFlightsSettings,
}: StrategyStageRendererProps) {
  // Unused props reserved for future use
  void _onReset;
  void _lastError;
  void _onRetry;

  // FIX: Subscribe to store to catch updates even if parent doesn't re-render
  // Priority: Store (Live) > Props (Parent passed)
  const effectiveTripInputs = useTripInputsWithFallback(tripInputs);
  const storeTiles = useDocumentStore((s) => s.document?.tiles);
  const effectiveTiles = storeTiles ?? tiles;

  // Heart preference system for SelectionsBar
  const preferredTileIds = useDocumentStore((s) => s.preferredTileIds);
  const toggleTilePreference = useDocumentStore((s) => s.toggleTilePreference);

  // Regeneration state from document store (managed by usePreferenceAutoRegen)
  const isRegenUpdating = useDocumentStore((s) => s.isRegenerating);
  const preferenceCount = preferredTileIds.size;

  // Unified regeneration state - combine plan regen (prop) and itinerary regen (store)
  // Shows overlay when EITHER is regenerating, locks UI during any regeneration
  const isAnyRegenerating = isRegenerating || isRegenUpdating;

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

  // Toast for infeasible specialists
  const { toast } = useToast();
  const prevInfeasibleRef = useRef<Set<string>>(new Set());

  // Show toast when specialists become infeasible or caveat (e.g., diving in Paris)
  useEffect(() => {
    const infullModeSections = (viewModel.strategy_sections ?? []).filter(
      section => section.feasibility_status === 'infeasible' || section.feasibility_status === 'caveat'
    );

    // Check for new infeasible sections
    const newInfeasible = infullModeSections.filter(
      section => !prevInfeasibleRef.current.has(section.specialist_type ?? section.title)
    );

    if (newInfeasible.length > 0) {
      const destination = effectiveTripInputs?.destination ?? destinationCard?.title ?? 'this destination';

      newInfeasible.forEach(section => {
        const specialistName = section.title || section.specialist_type || 'Activity';
        const alternatives = getAlternativeDestinations(section.specialist_type);

        toast(
          `${specialistName} unavailable in ${destination}. ${alternatives}`,
          { type: 'warning', duration: 5000 }
        );
      });
    }

    // Update ref with current infeasible sections
    prevInfeasibleRef.current = new Set(
      infullModeSections.map(s => s.specialist_type ?? s.title)
    );
  }, [viewModel.strategy_sections, effectiveTripInputs?.destination, destinationCard?.title, toast]);

  // hasTripContext = canGeneratePlan (destination + dates set)
  const nextAction = getNextAction(state, generation, canGeneratePlan);
  const currentStage = getStageFromState(state);
  const generating = isGenerating(generation);

  // =========================================================================
  // PATH A: Multi-Specialist Auto-Trigger Detection
  // =========================================================================
  // When multi-specialist trip is in S2 + has dates, we auto-trigger instead
  // of showing the "Build Itinerary" button. Show progress indicator instead.
  const isMultiSpecialist = isMultiSpecialistTrip(viewModel.executed_strategy_topics);
  const shouldShowAutoProgress = isMultiSpecialist && state === 'S2_STRATEGY_READY' && hasDates && generating;
  const shouldShowConflictBanner = conflictData != null;

  // Hide NextStepBar when:
  // 1. Multi-specialist trip in S2 (auto-trigger handles it)
  // 2. Conflict banner is showing
  // NextStepBar still shows for single-specialist trips (manual trigger)
  const hideNextStepBar = (isMultiSpecialist && state === 'S2_STRATEGY_READY' && hasDates) || shouldShowConflictBanner;

  // Compute progress stage for indicator
  const progressStage: ProgressStage = useMemo(() => {
    if (!generating) return 'success';
    const stage = generation?.stage;
    if (stage === 'itinerary') return 'building';
    // Check for constraint-related stages (may come from backend)
    if (stage === 'structure' || stage === 'strategy') return 'checking';
    return 'analyzing';
  }, [generating, generation?.stage]);

  // Compute streaming state for disabling pills
  const isStreaming = generating || isCommitting || isExpandingItinerary;

  // View navigation - two-mode system (PLANNING + BOOKING)
  const { activeMode, canViewBooking: _canViewBooking, activeView: _activeView, canViewSetup: _canViewSetup, canViewPlan: _canViewPlan } = useViewNavigation();

  // Two-mode system: use activeMode from hook, allow explicit override
  const effectiveMode: ViewMode = explicitMode ?? activeMode;

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

  // =========================================================================
  // PERF: Sub-memos to reduce computation on unrelated state changes
  // @see docs/ux_unified_architecture.md - Performance: Render Optimization
  // =========================================================================

  // MEMO 1: Display logic - changes when view state/density changes
  const displayLogic = useMemo(() => {
    const hasDates = !!effectiveTripInputs?.start_date;
    const hasTiles = effectiveTiles && Object.keys(effectiveTiles).length > 0;
    const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs);
    const isShowingMirrorLoader = generating && hasDates && !hasTiles;

    // Calculate actual trip duration from dates (more accurate than stored trip_duration)
    // This ensures POI filtering matches the current date range when dates change
    let tripDuration = effectiveTripInputs?.trip_duration ?? 3;
    if (effectiveTripInputs?.start_date && effectiveTripInputs?.end_date) {
      const start = new Date(effectiveTripInputs.start_date);
      const end = new Date(effectiveTripInputs.end_date);
      const diffDays = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;
      if (diffDays > 0) tripDuration = diffDays;
    }

    return {
      hasDates,
      hasTiles,
      density,
      isShowingMirrorLoader,
      tripDuration,
    };
  }, [state, viewModel.strategy_sections, effectiveTiles, effectiveTripInputs, generating]);

  // MEMO 2: Specialist data - changes when strategy_sections change
  // Pre-computed for ghost/bridge modes to avoid inline recalculation
  const specialistData = useMemo(() => {
    const fullModeSections = (viewModel.strategy_sections ?? []).filter(
      section => section.feasibility_status !== 'infeasible' && section.feasibility_status !== 'caveat'
    );
    const totalConstraints = fullModeSections.reduce(
      (acc, s) => acc + (s.constraints_applied?.length ?? 0),
      0
    );
    const ghostDuration = effectiveTripInputs?.trip_duration ?? 5;
    const ghostDayCards = generateGhostDayCards(fullModeSections, ghostDuration);
    const ghostHasDuration = !!effectiveTripInputs?.end_date || effectiveTripInputs?.trip_duration != null;

    return {
      fullModeSections,
      totalConstraints,
      ghostDayCards,
      ghostHasDuration,
      filteredViewModel: {
        ...viewModel,
        strategy_sections: fullModeSections,
      } as PlanViewModel,
    };
  }, [viewModel, effectiveTripInputs?.trip_duration, effectiveTripInputs?.end_date]);

  // Plan content - heavy, needs persistence
  // Uses computeDataDensity for unified rendering logic
  // @see docs/ux_unified_architecture.md Section VII - Data Density Levels
  const planContent = useMemo(() => {
    // PERF: Use pre-computed display logic from sub-memo
    const { density, isShowingMirrorLoader, tripDuration } = displayLogic;

    // MIRROR LOADER: Show skeleton when auto-fetching tiles after dates are set
    // @see docs/ux_unified_architecture.md Section VI - "Mirror Loader Strategy"
    // Rule: "Never auto-switch to an empty container"
    if (isShowingMirrorLoader) {
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

    // EMPTY: S0 without specialist content - hero is the view
    if (density === 'empty') {
      return null;
    }

    // PERF: Use pre-computed specialist data from sub-memo
    const {
      fullModeSections,
      filteredViewModel,
    } = specialistData;
    // Access ghostDayCards, ghostHasDuration, totalConstraints via specialistData.* in JSX

    // GHOST: S0 with specialist content - show "Planning Intelligence" panel + preview timeline
    // Cards are collapsed by default in SETUP mode - user can expand to see details
    // This ensures constraint visibility BEFORE date selection (core value prop)
    if (density === 'ghost') {
      return (
        <div className="p-4 space-y-4">
          {/* READY TO PLAN BANNER - prompts user to set dates after exploration */}
          {destinationCard?.title && fullModeSections.length > 0 && (
            <ReadyToPlanBanner
              destination={destinationCard.title}
              questionsAsked={fullModeSections.length}
              onStartPlanning={() => onOpenSheet?.('dates')}
              className="mb-2"
            />
          )}

          {/* PLANNING INTELLIGENCE HEADER */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                Planning Intelligence
              </h3>
            </div>
            {specialistData.totalConstraints > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium">
                {specialistData.totalConstraints} constraint{specialistData.totalConstraints > 1 ? 's' : ''} applied
              </span>
            )}
          </div>

          {/* SPECIALIST CARDS (collapsed by default in SETUP mode) */}
          <S2StrategyView
            viewModel={filteredViewModel}
            destinationCard={destinationCard}
            pendingTopics={viewModel.pending_strategy_topics}
            executedTopics={viewModel.executed_strategy_topics}
            tiles={{}} // No tiles in SETUP mode
            tripInputs={effectiveTripInputs}
            density="ghost"
            autoExpandOnLoad={false} // Cards stay collapsed in SETUP
            onOpenActivitySettings={onOpenActivitySettings}
          />

          {/* GHOST TIMELINE (preview of activities) */}
          <TimelineThread
            dayCards={specialistData.ghostDayCards}
            isDraft={true}
            showPriceEstimates={false}
            hasDuration={specialistData.ghostHasDuration}
            startDate={effectiveTripInputs?.start_date ?? null}
            onSelectNights={onSelectNights}
            onOpenDatePicker={() => onOpenSheet?.('dates')}
            onOpenStaysSettings={onOpenStaysSettings}
            onOpenFlightsSettings={onOpenFlightsSettings}
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
      // PERF: Use pre-computed feasible sections from specialistData
      const sections = specialistData.fullModeSections;
      const bridgeFilteredViewModel = filteredViewModel;
      // U5: Pass destination for demo POI fallback (use fallback chain for reliable lookup)
      // Bridge mode: no itinerary yet, show all specialist suggestions
      const effectiveDestination = effectiveTripInputs?.destination ?? destinationCard?.title;
      const mapPOIs = extractPOIsFromSections(sections, effectiveDestination);

      // Get destination coordinates for map center
      const bridgeDestCoords = getDestinationCoords(destinationCard?.title);
      const bridgeMapCenter = bridgeDestCoords
        ? { lng: bridgeDestCoords[0], lat: bridgeDestCoords[1], zoom: 10 }
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

      // SETUP vs PLAN mode detection handled via displayLogic.hasDates
      // Constraints count handled via specialistData.totalConstraints

      return (
        <div className="flex flex-col lg:flex-row gap-6 p-4">
          {/* Left Column: Strategy Cards Only (no timeline) */}
          <div className="flex-1 min-w-0 space-y-4">
            {/* READY TO PLAN BANNER - prompts user to set dates after exploration */}
            {!displayLogic.hasDates && destinationCard?.title && sections.length > 0 && (
              <ReadyToPlanBanner
                destination={destinationCard.title}
                questionsAsked={sections.length}
                onStartPlanning={() => onOpenSheet?.('dates')}
                className="mb-2"
              />
            )}

            {/* PLANNING INTELLIGENCE HEADER (SETUP mode only - before dates) */}
            {!displayLogic.hasDates && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-lg">⚡</span>
                  <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                    Planning Intelligence
                  </h3>
                </div>
                {specialistData.totalConstraints > 0 && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium">
                    {specialistData.totalConstraints} constraint{specialistData.totalConstraints > 1 ? 's' : ''} applied
                  </span>
                )}
              </div>
            )}

            {/* Strategy Cards - collapsed in SETUP (no dates), auto-expand in PLAN (has dates) */}
            <S2StrategyView
              viewModel={bridgeFilteredViewModel}
              destinationCard={destinationCard}
              pendingTopics={viewModel.pending_strategy_topics}
              executedTopics={viewModel.executed_strategy_topics}
              tiles={{}} // Empty - no booking tiles in bridge mode
              tripInputs={effectiveTripInputs}
              density="bridge"
              autoExpandOnLoad={displayLogic.hasDates} // SETUP = collapsed, PLAN = brief auto-expand
              onOpenActivitySettings={onOpenActivitySettings}
            />
          </div>

          {/* Right Column: Map (Fixed Width on Desktop) - shows destination pin or POIs */}
          <div className="hidden lg:block w-[350px] shrink-0">
            {/* Explicit height wrapper ensures Mapbox initializes correctly */}
            <div style={{ height: 400 }} className="rounded-xl overflow-hidden sticky top-4">
              {bridgeMapItems.length > 0 ? (
                <MapErrorBoundary className="h-full w-full">
                  <InteractiveMap
                    items={bridgeMapItems}
                    activeItemId={null}
                    defaultCenter={bridgeMapCenter}
                    className="h-full w-full"
                  />
                </MapErrorBoundary>
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

    // PERF: fullModeSections and filteredViewModel already destructured from specialistData above

    // Get destination coordinates for map (used in P3+ only)
    const destCoords = getDestinationCoords(destinationCard?.title);
    const mapCenter = destCoords
      ? { lng: destCoords[0], lat: destCoords[1], zoom: 8 }
      : { lng: 0, lat: 0, zoom: 4 }; // Fallback world view

    // Desktop: Show sticky map sidebar when destination is set
    // Map appears immediately when destination is known, not just after itinerary
    const showDesktopMap = isDesktop && !!destCoords;

    // U5: Extract POIs from actual itinerary (day_cards) when available, else from strategy sections
    // This ensures map pins match the generated itinerary, not the specialist's original suggestions
    const fullModeDestination = effectiveTripInputs?.destination ?? destinationCard?.title;
    const fullModePOIs = extractPOIsFromDayCards(
      viewModel.day_cards,
      fullModeSections,
      fullModeDestination
    );

    // Destination pin for the map center
    const destinationMarker: import('@/components/map/InteractiveMap').MapItem[] = destCoords
      ? [{
          id: 'destination-pin',
          title: destinationCard?.title || 'Destination',
          type: 'destination',
          coordinates: { lat: destCoords[1], lng: destCoords[0] },
        }]
      : [];

    // U5: Combine destination marker + POIs for full mode map
    const fullModeMapItems = [
      ...destinationMarker,
      ...fullModePOIs,
    ];

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
            {/* ALWAYS show specialist cards + Trip DNA bar when feasible sections exist */}
            {fullModeSections.length > 0 && (
              <>
                {/* Specialist cards - always visible (ABOVE) */}
                <S2StrategyView
                  key={`strategy-${destinationCard?.title}`}
                  viewModel={filteredViewModel}
                  destinationCard={destinationCard}
                  onRefineAssumptions={onRefineAssumptions}
                  canExpandToItinerary={viewModel.can_expand_to_itinerary ?? false}
                  pendingTopics={viewModel.pending_strategy_topics}
                  executedTopics={viewModel.executed_strategy_topics}
                  tiles={effectiveTiles}
                  tripInputs={effectiveTripInputs}
                  density={density}
                  onOpenActivitySettings={onOpenActivitySettings}
                />
                {/* Trip DNA bar - U6: Shows ENGINE CONSTRAINTS only (thesis proof) */}
                {(() => {
                  // Filter: only niche specialists (diving, hiking, skiing), not local_expert/general
                  const NICHE_SPECIALISTS = ['diving', 'hiking', 'skiing', 'cycling', 'boating'];
                  const engineConstraints = fullModeSections
                    .filter((s) => NICHE_SPECIALISTS.includes(s.specialist_type || ''))
                    .flatMap((s) => s.constraints_applied || []);

                  if (engineConstraints.length === 0) return null;

                  // Short label: label > reason (truncated) > rule (title-cased)
                  // Matches chat language ("24h No-Fly Buffer" not "No Fly 24h")
                  const getShortLabel = (c: { label?: string; rule?: string; reason?: string }) =>
                    c.label ||
                    (c.reason && c.reason.length > 30 ? c.reason.slice(0, 27) + '…' : c.reason) ||
                    (c.rule?.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())) ||
                    'Constraint';

                  return (
                    <div className="flex items-center gap-2 my-4 mx-4 p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800/60 border border-zinc-300 dark:border-zinc-700">
                      <span className="text-xs uppercase font-semibold text-zinc-500 dark:text-zinc-400 shrink-0">Trip DNA:</span>
                      <div className="flex gap-2 flex-wrap overflow-x-auto no-scrollbar">
                        {engineConstraints.map((c, i) => (
                          <span
                            key={`${c.rule}-${i}`}
                            title={c.reason || c.rule?.replace(/_/g, ' ')}
                            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white dark:bg-zinc-800/40 border border-amber-300 dark:border-amber-600/50 text-xs font-medium whitespace-nowrap"
                          >
                            <Shield className="w-3 h-3 text-amber-600 dark:text-amber-400 shrink-0" />
                            <span className="truncate max-w-[180px] sm:max-w-[240px] md:max-w-none">{getShortLabel(c)}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </>
            )}

            {/* Regeneration overlay - unified for plan AND itinerary regeneration */}
            {isAnyRegenerating && (
              <div className="absolute inset-0 z-10 flex items-start justify-center pt-20 bg-background/60 backdrop-blur-[1px]">
                <div className="flex flex-col items-center gap-3 rounded-lg bg-card/90 px-6 py-4 shadow-lg border border-border">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  <p className="text-sm font-medium text-muted-foreground">
                    {isRegenUpdating ? 'Updating itinerary...' : 'Updating plan...'}
                  </p>
                </div>
              </div>
            )}
          </section>

          {/* ORIGIN PROMPT - shows after specialists when origin not set */}
          {state === 'S2_STRATEGY_READY' &&
            effectiveTripInputs?.destination &&
            effectiveTripInputs?.start_date &&
            effectiveTripInputs?.end_date &&
            !effectiveTripInputs?.origin &&
            (viewModel.executed_strategy_topics?.length ?? 0) >= 2 && (
              <div className="px-4 mb-4">
                <OriginPromptCard
                  onSetOrigin={(origin) => {
                    useDocumentStore.getState().commitTripInputs({ origin });
                  }}
                />
              </div>
            )}

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
                onOpenStaysSettings={onOpenStaysSettings}
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
                  <MapErrorBoundary className="h-full w-full">
                    <InteractiveMap
                      items={fullModeMapItems}
                      activeItemId={null}
                      defaultCenter={mapCenter}
                      className="h-full w-full"
                    />
                  </MapErrorBoundary>
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
                {/* Relative wrapper for regeneration overlay */}
                <div className="relative">
                  <TimelineThread
                    dayCards={viewModel.day_cards ?? []}
                    variant={computeTimelineVariant(state)}
                    useRichBlocks={true}
                    savedTileIds={savedTileIds}
                    onOpenStaysSettings={onOpenStaysSettings}
                    onOpenFlightsSettings={onOpenFlightsSettings}
                  />

                  {/* Regeneration overlay - dims timeline during update */}
                  {isRegenUpdating && (
                    <div className="absolute inset-0 bg-black/50 z-10 flex items-center justify-center rounded-lg">
                      <div className="flex items-center gap-2 text-white bg-zinc-900/80 px-4 py-2 rounded-full">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span className="text-sm">Updating with {preferenceCount} preferences...</span>
                      </div>
                    </div>
                  )}
                </div>
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

        {/* RIGHT COLUMN: Sticky full-height map - shows when destination is set (Desktop only) */}
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
              <div className="sticky top-0 h-screen overflow-hidden">
                <div className="h-full w-full">
                  <MapErrorBoundary className="h-full w-full">
                    <InteractiveMap
                      items={fullModeMapItems}
                      activeItemId={null}
                      defaultCenter={mapCenter}
                      className="h-full w-full"
                    />
                  </MapErrorBoundary>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }, [
    // PERF: Sub-memos reduce recomputation - density/specialist data pre-computed
    displayLogic,
    specialistData,
    // State & view model
    state,
    viewModel,
    destinationCard,
    // Callbacks (should be stable via useCallback in parent)
    canGeneratePlan,
    onRefineAssumptions,
    onExpandToItinerary,
    onBuildPlan,
    onFinalizePlan,
    onSelectNights,
    onOpenSheet,
    onSaveTile,
    toggleTilePreference,
    scrollToTile,
    // Remaining state dependencies
    hasEverHadPlan,
    effectiveTiles,
    isDesktop,
    effectiveTripInputs,
    isRegenerating,
    isRegenUpdating, // Store selector for preference-based regeneration
    isFinalizing,
    isExpandingItinerary,
    generation,
    savedTileIds,
    effectiveMode,
    hasItineraryContent,
    preferredTileIds,
    // NOTE: onOpenActivitySettings, onOpenFlightsSettings, onOpenStaysSettings intentionally
    // excluded - they're inline arrows in parent, adding them defeats memoization
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
      onOpenStaysSettings={onOpenStaysSettings}
    />
  ), [state, effectiveTiles, generation, viewModel.strategy_sections, savedTileIds, onSaveTile, effectiveTripInputs?.start_date, onOpenStaysSettings]);

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
          isCollapsed={isCollapsed}
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
        isCollapsed={!isDesktop && isCollapsed}
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
      <AnimatePresence mode="wait">
        {/* PATH A: Auto-Progress Indicator for multi-specialist trips */}
        {shouldShowAutoProgress && effectiveMode === 'planning' && (
          <motion.div
            key="progress-indicator"
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{
              type: 'spring',
              stiffness: SPRING_CONFIG.SLIDE.stiffness,
              damping: SPRING_CONFIG.SLIDE.damping,
            }}
            className="sticky bottom-6 z-40 w-full justify-center pointer-events-none mt-8 hidden lg:flex"
          >
            <div className="pointer-events-auto w-fit mx-auto max-w-md">
              <ItineraryProgressIndicator
                stage={progressStage}
                specialists={viewModel.executed_strategy_topics ?? []}
                progress={generation?.pct}
                message={generation?.message}
              />
            </div>
          </motion.div>
        )}

        {/* PATH A: Conflict Resolution Banner */}
        {shouldShowConflictBanner && effectiveMode === 'planning' && (
          <motion.div
            key="conflict-banner"
            initial={{ y: 80, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 80, opacity: 0 }}
            transition={{
              type: 'spring',
              stiffness: SPRING_CONFIG.SLIDE.stiffness,
              damping: SPRING_CONFIG.SLIDE.damping,
            }}
            className="sticky bottom-6 z-40 w-full justify-center pointer-events-none mt-8 hidden lg:flex"
          >
            <div className="pointer-events-auto w-fit mx-auto max-w-lg">
              <ConflictResolutionBanner
                conflict={conflictData!}
                currentDays={effectiveTripInputs?.trip_duration ?? undefined}
                onResolve={(resolution) => onResolveConflict?.(resolution)}
              />
            </div>
          </motion.div>
        )}

        {/* Standard NextStepBar for single-specialist trips */}
        {nextAction && effectiveMode === 'planning' && !hideNextStepBar && (
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
              nextAction={nextAction}
            />
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}

export default StrategyStageRenderer;
