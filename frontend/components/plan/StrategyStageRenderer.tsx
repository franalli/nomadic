/* eslint no-unused-vars: ["error", { "args": "none" }] */
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
 * │ PlanHeader (sticky top)     │  ← Hero image + summary pills
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
import { AlertTriangle, CheckCircle, Clock, Loader2,Shield  } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { useScrollCollapse } from '@/hooks/useScrollCollapse';
import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { useViewNavigation } from '@/hooks/useViewNavigation';
import { fillDay } from '@/lib/api';
import { guardedEnforcePolicy } from '@/lib/contentPolicyGuard';
import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import { isFillDayCooldownActive } from '@/lib/fillDayGuards';
import {
  calculateMapCenter,
  extractPOIsFromDayCards,
  extractPOIsFromSections,
  generateGhostDayCards,
  hasSpecialistContent,
} from '@/lib/ghost-timeline-adapter';
import { NICHE_SPECIALIST_IDS } from '@/lib/specialists';
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
// Stable Empty Arrays (prevent infinite re-render loops with Zustand selectors)
// =============================================================================
const EMPTY_CONSTRAINTS_VALIDATED: Array<{
  constraint_id: string;
  rule: string;
  status: 'satisfied';
  specialist: string;
  label: string;
}> = [];
const EMPTY_CONSTRAINT_VIOLATIONS: Array<{
  code: string;
  message: string;
  severity: string;
  category: string;
  rule?: string;
}> = [];

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
  tiles: Record<string, Tile> | undefined
): DataDensity {
  const hasSpecialist = hasSpecialistContent(strategySections);
  const hasTiles = tiles && Object.keys(tiles).length > 0;

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


import {
  REVEAL_TIMING,
  SPRING_CONFIG,
} from '@/lib/animation-config';

/** Style for left content column when desktop map sidebar is visible */
const DESKTOP_MAP_CONTENT_STYLE = { minWidth: 720, maxWidth: 900 } as const;

import { BookingDrawer } from './booking/BookingDrawer';
import { BookingSection } from './BookingSection';
import { DestinationMapPlaceholder } from './DestinationMapPlaceholder';
import { ItineraryProgressIndicator, type ProgressStage } from './ItineraryProgressIndicator';
import { NextStepBar } from './NextStepBar';
import { OriginPromptCard } from './OriginPromptCard';
import { PlanHeader } from './PlanHeader';
import {
  type GenerationState,
  getNextAction,
  isGenerating,
  isMultiSpecialistTrip,
} from './planStateHelpers';
import { S2StrategyView } from './stages/S2StrategyView';
import { getShortConstraintLabel } from './stages/StrategyHero';
import { TimelineSkeleton } from './timeline/TimelineSkeleton';
import { TimelineThread, type TimelineVariant } from './TimelineThread';

/**
 * Compute timeline variant based on current planning state.
 * - S3_ITINERARY_READY: 'real' (finalized itinerary)
 * - S3_EDITING/S2_STRATEGY_READY: 'draft' (work in progress)
 * - Others: 'ghost' (preview)
 * @see docs/ux_unified_architecture.md
 */
function computeTimelineVariant(state: PlanViewState): TimelineVariant {
  if (state === 'S3_ITINERARY_READY') return 'real';
  if (state === 'S3_EDITING' || state === 'S2_STRATEGY_READY') return 'draft';
  return 'ghost';
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
  /** Handler to trigger plan generation from S0 "Build plan" CTA */
  onBuildPlan?: () => void;
  onExpandToItinerary?: () => Promise<void>;
  /** Callback to finalize plan and navigate to Book view */
  onFinalizePlan?: () => void;
  /** Whether finalization is in progress */
  isFinalizing?: boolean;
  onRefineAssumptions?: () => void;
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
  onBuildPlan,
  onExpandToItinerary,
  onFinalizePlan,
  isFinalizing = false,
  onRefineAssumptions,
  savedTileIds = new Set(),
  onSaveTile,
  tripInputs,
  onOpenSheet,
  isCommitting = false,
  hasEverHadPlan = false,
  isRegenerating = false,
  onSelectNights,
  mode: explicitMode,
  onOpenActivitySettings,
  onOpenStaysSettings,
  onOpenFlightsSettings,
}: StrategyStageRendererProps) {
  // FIX: Subscribe to store to catch updates even if parent doesn't re-render
  // Priority: Store (Live) > Props (Parent passed)
  const effectiveTripInputs = useTripInputsWithFallback(tripInputs);
  const {
    storeTiles,
    storeDayCardsRaw,
    preferredTileIds,
    toggleTilePreference,
    isRegenUpdating,
    constraintsValidated,
    constraintViolations,
  } = useDocumentStore(
    useShallow((s) => ({
      storeTiles: s.document?.tiles,
      storeDayCardsRaw: s.document?.day_cards,
      preferredTileIds: s.preferredTileIds,
      toggleTilePreference: s.toggleTilePreference,
      isRegenUpdating: s.isRegenerating,
      constraintsValidated: s.document?.constraints_validated ?? EMPTY_CONSTRAINTS_VALIDATED,
      constraintViolations: s.document?.constraint_violations ?? EMPTY_CONSTRAINT_VIOLATIONS,
    }))
  );

  // Compute fingerprint outside selector — avoids running on every store update
  const dayCardsFingerprint = useMemo(() => {
    const cards = storeDayCardsRaw;
    if (!cards || cards.length === 0) return null;
    const blockIds = cards
      .flatMap((c) => c.blocks || [])
      .filter((b) => b.coordinates?.lat != null && b.coordinates?.lng != null)
      .map((b) => b.id)
      .join(',');
    return blockIds ? `${cards.length}:${blockIds}` : null;
  }, [storeDayCardsRaw]);
  const effectiveTiles = storeTiles ?? tiles;

  // Stabilize day_cards reference: only snapshot from store when fingerprint changes.
  // mergeEnvelope creates new DayCard objects on every update, so raw selector
  // returns a new ref each time -> causes spurious re-renders and repeated POI extraction.
  const stableDayCardsRef = useRef(storeDayCardsRaw);
  const prevFingerprintRef = useRef(dayCardsFingerprint);
  if (dayCardsFingerprint !== prevFingerprintRef.current) {
    prevFingerprintRef.current = dayCardsFingerprint;
    stableDayCardsRef.current = storeDayCardsRaw;
  }
  const effectiveDayCards = stableDayCardsRef.current ?? viewModel.day_cards;

  // Regeneration state from document store (managed by usePreferenceAutoRegen)
  const preferenceCount = preferredTileIds.size;

  // Memoized sets for efficient rule lookup
  const validatedRules = useMemo(
    () => new Set(constraintsValidated.map((v) => v.rule)),
    [constraintsValidated]
  );
  const violatedRules = useMemo(
    () => new Set(constraintViolations.filter((v) => v.rule).map((v) => v.rule!)),
    [constraintViolations]
  );

  // Unified regeneration state - combine plan regen (prop) and itinerary regen (store)
  // Shows overlay when EITHER is regenerating, locks UI during any regeneration
  const isAnyRegenerating = isRegenerating || isRegenUpdating;

  // Data guard: strategy_sections array has items (distinct from hasStrategy state check)
  const hasSectionData = (viewModel.strategy_sections?.length ?? 0) > 0;

  // Get desktop state for mobile-specific rendering
  const isDesktop = useIsDesktop();

  // Scroll collapse tracking for mobile header optimization
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const isCollapsed = useScrollCollapse(scrollContainerRef, { threshold: 60, hysteresis: 15 });

  // Timeline ref for auto-scroll
  const timelineSectionRef = useRef<HTMLDivElement>(null);
  const prevHasItineraryRef = useRef(false);
  // Scroll freeze ref - captures position when expansion starts
  const frozenScrollRef = useRef<number | null>(null);

  // Enforce content policy in development
  useEffect(() => {
    guardedEnforcePolicy(state, viewModel);
  }, [state, viewModel]);

  // Track hasItineraryContent for auto-scroll trigger
  const hasItineraryContent: boolean = state === 'S3_ITINERARY_READY' || state === 'S3_EDITING' ||
    Boolean(viewModel.day_cards && viewModel.day_cards.length > 0);

  // Toggle for showing/hiding specialist cards in S3 (collapsed by default)
  const [showConstraints, setShowConstraints] = useState(false);
  const { toast } = useToast();

  // Booking drawer state - allows FreeDayCard "Browse Activities" to open the drawer
  const [bookingDrawerCategory, setBookingDrawerCategory] = useState<'hotel' | 'flight' | 'activity' | null>(null);
  const [bookingDrawerPinnedDay, setBookingDrawerPinnedDay] = useState<number | null>(null);
  const lastFillDayRequestAtRef = useRef(0);
  const handleOpenBookingDrawer = useCallback((category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => {
    setBookingDrawerCategory(category);
    setBookingDrawerPinnedDay(dayNumber ?? null);
  }, []);
  const handleCloseBookingDrawer = useCallback(() => {
    setBookingDrawerCategory(null);
    setBookingDrawerPinnedDay(null);
  }, []);

  // Wire BookingDrawer "Add" button: pinned day → fill-day API, otherwise preference toggle (idempotent)
  const handleSaveTile = useCallback(async (tile: Tile) => {
    if (bookingDrawerPinnedDay != null) {
      const store = useDocumentStore.getState();
      const generationInFlight = isGenerating(generation) || isCommitting || isExpandingItinerary;
      if (generationInFlight || store.currentRunId) {
        handleCloseBookingDrawer();
        toast('Please wait until itinerary updates complete');
        return;
      }
      const now = Date.now();
      if (isFillDayCooldownActive(now, lastFillDayRequestAtRef.current)) {
        handleCloseBookingDrawer();
        toast('Please wait a moment before adding another activity');
        return;
      }
      // Guard: skip if expand-itinerary is running
      if (store.expandInProgress) {
        handleCloseBookingDrawer();
        return;
      }
      // Per-day mutex: prevents concurrent calls from any path
      if (!store.claimFillDay(bookingDrawerPinnedDay)) {
        handleCloseBookingDrawer();
        return;
      }
      lastFillDayRequestAtRef.current = now;
      store.claimMutation();
      // Close drawer immediately to prevent repeat clicks
      handleCloseBookingDrawer();
      // Pin browsed tile to specific day via fill-day API
      try {
        const result = await fillDay(bookingDrawerPinnedDay, undefined, [tile.id]);
        if (result?.day_card) {
          useDocumentStore.getState().replaceDayCard(
            bookingDrawerPinnedDay, result.day_card, result.version, result.tiles
          );
        }
      } catch (err) {
        const is409 = err instanceof Error && err.message.includes('409');
        const is429 = err instanceof Error && err.message.includes('429');
        if (is409) {
          debugLog(`[fillDay] day=${bookingDrawerPinnedDay} already filled (409), refreshing card`);
          return;
        }
        if (is429) {
          toast('Too many requests. Please wait a moment and try again');
          return;
        }
        console.error('[StrategyStageRenderer] fill-day failed:', err);
      } finally {
        useDocumentStore.getState().releaseMutation();
        useDocumentStore.getState().releaseFillDay(bookingDrawerPinnedDay);
      }
      return;
    }
    // Existing global preference path (unchanged)
    if (onSaveTile) {
      onSaveTile(tile);
      return;
    }
    // Idempotent guard: toggleTilePreference is a toggle, so only call if not already preferred
    const { preferredTileIds: currentPrefs, toggleTilePreference: toggle } = useDocumentStore.getState();
    if (!currentPrefs.has(tile.id)) {
      toggle(tile.id);
    }
  }, [
    bookingDrawerPinnedDay,
    generation,
    handleCloseBookingDrawer,
    isCommitting,
    isExpandingItinerary,
    onSaveTile,
    toast,
  ]);

  // Debounced density state to prevent layout flash during transitions
  // Updated via requestAnimationFrame to let browser paint current frame first
  const [stableDensity, setStableDensity] = useState<'empty' | 'ghost' | 'bridge' | 'full'>('empty');

  // Capture scroll position when expansion starts (before DOM changes)
  useEffect(() => {
    if (isExpandingItinerary && !hasItineraryContent) {
      frozenScrollRef.current = window.scrollY;
    }
  }, [isExpandingItinerary, hasItineraryContent]);

  // Restore scroll position synchronously BEFORE paint when itinerary arrives
  // useLayoutEffect runs after DOM mutations but before browser paint
  useLayoutEffect(() => {
    if (hasItineraryContent && !prevHasItineraryRef.current && frozenScrollRef.current !== null) {
      window.scrollTo(0, frozenScrollRef.current);
      frozenScrollRef.current = null; // Clear after restore
    }
  }, [hasItineraryContent]);

  // Smooth scroll to timeline after content arrives (runs after paint)
  useEffect(() => {
    if (hasItineraryContent && !prevHasItineraryRef.current) {
      const timer = setTimeout(() => {
        timelineSectionRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      }, 100); // Short delay - scroll freeze already handled
      return () => clearTimeout(timer);
    }
    prevHasItineraryRef.current = hasItineraryContent;
  }, [hasItineraryContent]);

  // Toast for infeasible specialists
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
        const reason = section.feasibility_reason || 'Try a different destination.';

        toast(
          `${specialistName} unavailable in ${destination}. ${reason}`,
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
  const generating = isGenerating(generation);

  // =========================================================================
  // PATH A: Multi-Specialist Auto-Trigger Detection
  // =========================================================================
  // When multi-specialist trip is in S2 + has dates, we auto-trigger instead
  // of showing the "Build Itinerary" button. Show progress indicator instead.
  const isMultiSpecialist = isMultiSpecialistTrip(viewModel.executed_strategy_topics);
  const shouldShowAutoProgress = isMultiSpecialist && state === 'S2_STRATEGY_READY' && hasDates && generating;
  // Hide NextStepBar when multi-specialist trip in S2 (auto-trigger handles it)
  // NextStepBar still shows for single-specialist trips (manual trigger)
  const hideNextStepBar = isMultiSpecialist && state === 'S2_STRATEGY_READY' && hasDates;

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
  const { activeMode } = useViewNavigation();

  // Two-mode system: use activeMode from hook, allow explicit override
  const effectiveMode: ViewMode = explicitMode ?? activeMode;

  // =========================================================================
  // UNIFIED PLANNING VIEW - Preferences & Scroll State
  // =========================================================================

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
    const density = computeDataDensity(state, viewModel.strategy_sections, effectiveTiles);
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

  // Debounce density transitions with rAF to prevent layout flash
  // Ensures browser paints current frame before switching layouts
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      setStableDensity(displayLogic.density);
    });
    return () => cancelAnimationFrame(raf);
  }, [displayLogic.density]);

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

  // MEMO 3: POI extraction - isolated from planContent to prevent 50+ recalculations
  // Hard stop: Only extract POIs when day_cards exist (no fallback to strategy sections)
  // DEMO_POIS from destination-coords.ts handles pre-itinerary map via destination pin logic
  const fullModePOIs = useMemo(() => {
    // Hard stop — no day_cards, no POIs (DEMO_POIS handles pre-itinerary)
    if (!dayCardsFingerprint) {
      return [];
    }
    const destination = effectiveTripInputs?.destination ?? destinationCard?.title;
    return extractPOIsFromDayCards(
      effectiveDayCards,
      specialistData.fullModeSections,
      destination,
      dayCardsFingerprint
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- dayCardsFingerprint is content-based proxy
  }, [dayCardsFingerprint, effectiveTripInputs?.destination, destinationCard?.title]);

  // Plan content - heavy, needs persistence
  // Uses computeDataDensity for unified rendering logic
  // @see docs/ux_unified_architecture.md Section VII - Data Density Levels
  const planContent = useMemo(() => {
    // PERF: Use pre-computed display logic from sub-memo
    const { isShowingMirrorLoader, tripDuration } = displayLogic;
    // Use stableDensity for layout decisions (debounced via rAF to prevent flash)
    const density = stableDensity;

    // MIRROR LOADER: Show skeleton when auto-fetching tiles after dates are set
    // @see docs/ux_unified_architecture.md Section VI - "Mirror Loader Strategy"
    // Rule: "Never auto-switch to an empty container"
    if (isShowingMirrorLoader) {
      return (
        <div className="p-4 space-y-6">
          {/* Status indicator */}
          <div className="flex items-center gap-2">
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

    // EMPTY: S0 without specialist content — PlanHeader topo + tagline shows through
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
          {/* PLANNING INTELLIGENCE HEADER */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                Planning Intelligence
              </h3>
            </div>
            {specialistData.totalConstraints > 0 && (
              <span className={`${DS.textSize.micro} px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium`}>
                {specialistData.totalConstraints} constraint{specialistData.totalConstraints > 1 ? 's' : ''} applied
              </span>
            )}
          </div>

          {/* SPECIALIST CARDS (collapsed by default in SETUP mode) */}
          <S2StrategyView
            viewModel={filteredViewModel}
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
          <div className="text-center pt-4 pb-6">
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

      // Map center: derive from POIs, fall back to world view
      const bridgeMapCenter = mapPOIs.length > 0
        ? calculateMapCenter(mapPOIs)
        : { lat: 20, lng: 0, zoom: 2 };

      const bridgeMapItems = mapPOIs;

      // SETUP vs PLAN mode detection handled via displayLogic.hasDates
      // Constraints count handled via specialistData.totalConstraints

      return (
        <div className="flex flex-col lg:flex-row gap-6 p-4">
          {/* Left Column: Strategy Cards Only (no timeline) */}
          <div className="flex-1 min-w-0 space-y-4">
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
                  <span className={`${DS.textSize.micro} px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium`}>
                    {specialistData.totalConstraints} constraint{specialistData.totalConstraints > 1 ? 's' : ''} applied
                  </span>
                )}
              </div>
            )}

            {/* Strategy Cards - collapsed in SETUP (no dates), auto-expand in PLAN (has dates) */}
            <S2StrategyView
              viewModel={bridgeFilteredViewModel}
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
          <div className="hidden w-[350px] shrink-0 lg:block">
            {/* Explicit height wrapper ensures Mapbox initializes correctly */}
            <div className="sticky top-4 h-[400px] overflow-hidden rounded-xl">
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

    // U5: POIs for full mode map - pre-computed in MEMO 3 (fullModePOIs) to avoid recalculation
    // See MEMO 3 above: extractPOIsFromDayCards is memoized with minimal dependencies
    // Fallback to section-based POIs when day_cards don't have coordinates yet
    const effectiveFullDest = effectiveTripInputs?.destination ?? destinationCard?.title;
    const sectionFallbackPOIs = fullModePOIs.length === 0
      ? extractPOIsFromSections(specialistData.fullModeSections, effectiveFullDest)
      : [];
    const fullModeMapItems = fullModePOIs.length > 0 ? fullModePOIs : sectionFallbackPOIs;

    // Map center: derive from POIs, fall back to world view
    const mapCenter = fullModeMapItems.length > 0
      ? calculateMapCenter(fullModeMapItems)
      : { lat: 20, lng: 0, zoom: 2 };

    // Desktop: Show sticky map sidebar when POIs exist (from day_cards or sections)
    const showDesktopMap = isDesktop && fullModeMapItems.length > 0;

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
          style={showDesktopMap ? DESKTOP_MAP_CONTENT_STYLE : undefined}
        >
          {/* SECTION 1: SPECIALISTS */}
          <section id="specialists-section" className="relative">
            {/* ALWAYS show specialist cards + Trip DNA bar when feasible sections exist */}
            {fullModeSections.length > 0 && (
              <>
                {/* Specialist cards - collapsible in S3 (itinerary ready) */}
                {!hasItineraryContent ? (
                  <S2StrategyView
                    key={`strategy-${destinationCard?.title}`}
                    viewModel={filteredViewModel}
                    onRefineAssumptions={onRefineAssumptions}
                    pendingTopics={viewModel.pending_strategy_topics}
                    executedTopics={viewModel.executed_strategy_topics}
                    tiles={effectiveTiles}
                    tripInputs={effectiveTripInputs}
                    density={density}
                    onOpenActivitySettings={onOpenActivitySettings}
                  />
                ) : (
                  <>
                    {showConstraints && (
                      <S2StrategyView
                        key={`strategy-${destinationCard?.title}`}
                        viewModel={filteredViewModel}
                        onRefineAssumptions={onRefineAssumptions}
                        pendingTopics={viewModel.pending_strategy_topics}
                        executedTopics={viewModel.executed_strategy_topics}
                        tiles={effectiveTiles}
                        tripInputs={effectiveTripInputs}
                        density={density}
                        onOpenActivitySettings={onOpenActivitySettings}
                      />
                    )}
                  </>
                )}
                {/* Trip DNA bar - U6: Shows ENGINE CONSTRAINTS with validation state */}
                {(() => {
                  // Filter: only niche specialists, not local_expert/general
                  // Exclude soft/info severity — only show blocking + strong constraints
                  const engineConstraints = fullModeSections
                    .filter((s) => NICHE_SPECIALIST_IDS.includes(s.specialist_type || ''))
                    .flatMap((s) => s.constraints_applied || [])
                    .filter((c) => {
                      const sev = (c as Record<string, string>).severity;
                      // Show if no severity set (legacy) or blocking/strong
                      return !sev || sev === 'blocking' || sev === 'strong';
                    });

                  if (engineConstraints.length === 0) return null;

                  // Short label: label > shortConstraintLabel(rule) - compact for mobile pills
                  const getShortLabel = (c: { label?: string; rule?: string; reason?: string }) =>
                    c.label ||
                    (c.rule ? getShortConstraintLabel(c.rule) : null) ||
                    'Constraint';

                  // Three-state styling: violated > validated > unchecked (with priority coloring)
                  const getPillStyle = (c: { rule?: string; type?: string; reason?: string }) => {
                    const rule = c.rule;
                    // Check both exact rule match AND partial match for robustness
                    const isViolated = rule && (
                      violatedRules.has(rule) ||
                      [...violatedRules].some(vr => vr?.includes(rule) || rule.includes(vr || ''))
                    );
                    const isValidated = rule && (
                      validatedRules.has(rule) ||
                      [...validatedRules].some(vr => vr?.includes(rule) || rule.includes(vr || ''))
                    );

                    if (isViolated) {
                      return {
                        // Amber with ring for violated - draws attention without anxiety
                        pillClass: 'bg-amber-50 dark:bg-amber-900/30 border-amber-400 dark:border-amber-500/60 ring-2 ring-amber-400/60',
                        iconClass: 'text-amber-600 dark:text-amber-400',
                        Icon: AlertTriangle,
                      };
                    }
                    if (isValidated) {
                      return {
                        // Emerald for validated - constraint satisfied
                        pillClass: 'bg-emerald-50 dark:bg-emerald-900/30 border-emerald-300 dark:border-emerald-600/50',
                        iconClass: 'text-emerald-600 dark:text-emerald-400',
                        Icon: CheckCircle,
                      };
                    }
                    // Unchecked: color by priority (blocking > strong > soft)
                    // Check type, rule, AND reason for keyword matching
                    const t = `${c.type || ''} ${c.rule || ''} ${c.reason || ''}`.toLowerCase();
                    // Blocking: safety constraints, flight buffers, altitude restrictions
                    // Blocking: safety constraints, flight buffers, altitude restrictions, scuba rules
                    const blocking = ['no_fly', 'no-fly', 'nofly', 'safety', 'altitude', 'buffer', '24h', '24 hour', 'diving', 'dive', 'scuba', 'decompression', 'fly', 'flight'];
                    // Strong: timing, equipment requirements
                    const strong = ['morning', 'footwear', 'gear', 'timing', 'equipment', 'certification'];

                    if (blocking.some(k => t.includes(k))) {
                      return {
                        // Light: red-600 for visibility | Dark: red-300
                        pillClass: 'border-red-500/40 bg-red-500/10 text-red-600 dark:border-red-500/40 dark:bg-red-500/15 dark:text-red-300',
                        iconClass: '', // Inherit from pill
                        Icon: Shield,
                      };
                    }
                    if (strong.some(k => t.includes(k))) {
                      return {
                        // Light: amber-600 for visibility | Dark: amber-300
                        pillClass: 'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-300',
                        iconClass: '', // Inherit from pill
                        Icon: Shield,
                      };
                    }
                    // Default soft priority
                    return {
                      // Light: zinc-600 for visibility | Dark: zinc-400
                      pillClass: 'border-zinc-400/40 bg-zinc-500/10 text-zinc-600 dark:border-zinc-500/40 dark:bg-zinc-500/15 dark:text-zinc-400',
                      iconClass: '', // Inherit from pill
                      Icon: Shield,
                    };
                  };

                  return (
                    <div className="flex items-start gap-2 my-4 mx-4 p-3 rounded-lg bg-zinc-100 dark:bg-zinc-950 border border-zinc-300 dark:border-zinc-700">
                      <span className="text-xs uppercase font-semibold text-zinc-500 dark:text-zinc-400 shrink-0 leading-[30px]">Trip DNA:</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap gap-2">
                          {engineConstraints.map((c, i) => {
                            const style = getPillStyle(c);
                            return (
                              <span
                                key={`${c.rule}-${i}`}
                                title={c.reason || c.rule?.replace(/_/g, ' ')}
                                className={cn(
                                  'inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full border text-xs font-medium whitespace-nowrap',
                                  style.pillClass
                                )}
                              >
                                {/* Icon by priority: blocking=AlertTriangle, strong=Clock, soft=Shield */}
                                {(() => {
                                  const t = `${c.type || ''} ${c.rule || ''} ${c.reason || ''}`.toLowerCase();
                                  const blocking = ['no_fly', 'no-fly', 'nofly', 'safety', 'altitude', 'buffer', '24h', '24 hour', 'diving', 'dive', 'scuba', 'decompression', 'fly', 'flight'];
                                  const strong = ['morning', 'footwear', 'gear', 'timing', 'equipment', 'certification'];
                                  if (blocking.some(k => t.includes(k))) {
                                    return <AlertTriangle className="w-4 h-4 shrink-0" />;
                                  }
                                  if (strong.some(k => t.includes(k))) {
                                    return <Clock className="w-4 h-4 shrink-0" />;
                                  }
                                  return <Shield className="w-4 h-4 shrink-0" />;
                                })()}
                                <span>{getShortLabel(c)}</span>
                              </span>
                            );
                          })}
                        </div>
                      </div>
                      {/* Toggle for specialist cards - inside Trip DNA bar, right-aligned */}
                      {hasItineraryContent && (
                        <button
                          type="button"
                          onClick={() => setShowConstraints(!showConstraints)}
                          className="text-xs text-zinc-500 hover:text-zinc-400 underline cursor-pointer shrink-0 ml-2 leading-[30px]"
                        >
                          {showConstraints ? 'Hide' : 'Details'}
                        </button>
                      )}
                    </div>
                  );
                })()}
              </>
            )}

            {/* Regeneration overlay - unified for plan AND itinerary regeneration */}
            {isAnyRegenerating && (
              <div className="absolute inset-0 z-10 flex items-start justify-center pt-20 bg-background/60 backdrop-blur-[1px]">
                <div className="flex flex-col items-center gap-4 rounded-lg bg-card/90 px-6 py-4 shadow-lg border border-border">
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
                hasStrategyContent={hasSectionData}
                savedTileIds={savedTileIds}
                onSaveTile={handleSaveTile}
                hasDates={!!effectiveTripInputs?.start_date}
                mode={effectiveMode}
                strategySections={viewModel.strategy_sections}
                onOpenStaysSettings={onOpenStaysSettings}
              />
              </motion.section>
            )}
          </AnimatePresence>

          {/* MOBILE ONLY: Inline map before timeline — only when POIs exist (not just destination pin) */}
          {!isDesktop && hasItineraryContent && fullModePOIs.length > 0 && (
            <section className="mt-4 px-4">
              {/* Explicit height wrapper ensures Mapbox initializes correctly */}
              <div className="h-[300px] overflow-hidden rounded-xl border border-border/50">
                <MapErrorBoundary className="h-full w-full">
                  <InteractiveMap
                    items={fullModeMapItems}
                    activeItemId={null}
                    defaultCenter={mapCenter}
                    className="h-full w-full"
                  />
                </MapErrorBoundary>
              </div>
            </section>
          )}

          {/* SECTION 3: TIMELINE - skeleton reserves space, then swaps to real content */}
          {/* Single conditional ensures skeleton and timeline occupy same DOM position */}
          {hasItineraryContent ? (
            <motion.section
              key="timeline-section"
              ref={timelineSectionRef}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
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
                  disableFillDayActions={isStreaming}
                  savedTileIds={savedTileIds}
                  onOpenBookingDrawer={handleOpenBookingDrawer}
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
          ) : isExpandingItinerary ? (
            /* Skeleton reserves ~300px BEFORE day_cards arrive - prevents layout jump */
            <section ref={timelineSectionRef} className="px-4 py-6 space-y-4 animate-pulse">
              {[1, 2].map(i => (
                <div key={i} className="space-y-2">
                  <div className="h-6 w-24 bg-zinc-200 dark:bg-zinc-800 rounded" />
                  <div className="h-20 bg-zinc-200/40 dark:bg-zinc-800/40 rounded-lg" />
                  <div className="h-20 bg-zinc-200/40 dark:bg-zinc-800/40 rounded-lg" />
                </div>
              ))}
              <div className="flex items-center justify-center gap-2 pt-4">
                <Loader2 className="w-4 h-4 animate-spin text-emerald-500" />
                <span className="text-sm text-muted-foreground">Building your itinerary...</span>
              </div>
            </section>
          ) : null}
        </div>

        {/* RIGHT COLUMN: Sticky full-height map - shows when destination is set (Desktop only) */}
        <AnimatePresence>
          {showDesktopMap && (
            <motion.div
              key="desktop-map"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3 }}
              className="w-[400px] max-w-[35vw] shrink-0"
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
  // eslint-disable-next-line react-hooks/exhaustive-deps -- onOpenActivitySettings, onOpenFlightsSettings, onOpenStaysSettings intentionally excluded: they're inline arrows in parent, adding them defeats memoization
  }, [
    // PERF: Sub-memos reduce recomputation - density/specialist data pre-computed
    displayLogic,
    specialistData,
    stableDensity, // Debounced density for layout decisions (prevents flash)
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
    handleSaveTile,
    toggleTilePreference,
    scrollToTile,
    // Remaining state dependencies
    hasEverHadPlan,
    effectiveTiles,
    fullModePOIs, // Pre-computed POIs from MEMO 3 (replaces inline extractPOIsFromDayCards)
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
    showConstraints,
    preferredTileIds,
    handleOpenBookingDrawer, // Stable (useCallback with empty deps) - wires FreeDayCard "Browse Activities"
    validatedRules,
    violatedRules,
    isAnyRegenerating,
    preferenceCount,
  ]);

  // Book content - full booking section view
  const bookContent = useMemo(() => (
    <BookingSection
      state={state}
      tiles={effectiveTiles}
      generation={generation}
      hasStrategyContent={hasSectionData}
      savedTileIds={savedTileIds}
      onSaveTile={handleSaveTile}
      hasDates={!!effectiveTripInputs?.start_date}
      mode="booking" // Book view is always in booking mode
      strategySections={viewModel.strategy_sections}
      onOpenStaysSettings={onOpenStaysSettings}
    />
  ), [state, effectiveTiles, generation, viewModel.strategy_sections, hasSectionData, savedTileIds, handleSaveTile, effectiveTripInputs?.start_date, onOpenStaysSettings]);

  // MOBILE: Simplified layout - no absolute positioning layer system
  // Desktop uses layers to preserve scroll position across view switches
  // Mobile uses SplitLayoutView tab switching instead
  if (!isDesktop) {
    return (
      <>
        <div className="flex flex-col h-full">
          {/* Hero hidden on mobile — TripStatusBar provides trip context */}

          {/* Content - direct render, scrollable */}
          <div
            ref={scrollContainerRef}
            className={cn(
              'flex-1 overflow-y-auto',
              nextAction && 'pb-32' // Space for sticky footer
            )}
          >
            {/* Content scrim for topo visibility */}
            <div className="relative min-h-full">
              <div className="pointer-events-none absolute inset-0 z-[1] bg-background/70 dark:bg-background/20" />
              <div className="relative z-[2]">{planContent}</div>
            </div>
          </div>

        </div>
        <BookingDrawer
          category={bookingDrawerCategory}
          tiles={effectiveTiles}
          savedTileIds={savedTileIds}
          onSave={handleSaveTile}
          onClose={handleCloseBookingDrawer}
          onOpenStaysSettings={onOpenStaysSettings}
          pinnedDayNumber={bookingDrawerPinnedDay}
        />
      </>
    );
  }

  // DESKTOP: Layer system for view switching with scroll preservation
  return (
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden">
      {/* Header - always visible, controls view navigation */}
      <PlanHeader
        destinationCard={destinationCard}
        isGenerating={generating}
        fallbackTitle={fallbackTitle}
        planViewState={state}
        isExpandingItinerary={isExpandingItinerary}
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

      {/* Booking Drawer - opened by FreeDayCard "Browse Activities" and GhostSlot clicks */}
      <BookingDrawer
        category={bookingDrawerCategory}
        tiles={effectiveTiles}
        savedTileIds={savedTileIds}
        onSave={handleSaveTile}
        onClose={handleCloseBookingDrawer}
        onOpenStaysSettings={onOpenStaysSettings}
        pinnedDayNumber={bookingDrawerPinnedDay}
      />
    </div>
  );
}

export default StrategyStageRenderer;
