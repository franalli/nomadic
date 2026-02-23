'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { useCallback, useMemo } from 'react';

import { useDocumentStore } from '@/state/documentStore';
import {
  computePlanningPhase,
  computePlanningProgress,
  type PlanningPhase,
  type ViewMode,
} from '@/types/plan-envelope';

// =============================================================================
// Types
// =============================================================================

/**
 * @deprecated Legacy type kept for components not yet migrated.
 * Maps: setup/plan → 'planning', book → 'booking'
 */
type ViewName = 'setup' | 'plan' | 'book';

interface ViewUnlockState {
  planning: { unlocked: boolean; reason: string | null };
  booking: { unlocked: boolean; reason: string | null };
}

interface UseViewNavigationReturn {
  // === Two-Mode System (New) ===
  /** Current active mode: 'planning' or 'booking' */
  activeMode: ViewMode;
  /** Navigate to a mode */
  navigateToMode: (mode: ViewMode) => boolean;
  /** Whether booking mode is unlocked */
  canViewBooking: boolean;
  /** Unlock state with reasons */
  unlockState: ViewUnlockState;
  /** Current planning phase (progress within PLANNING mode) */
  planningPhase: PlanningPhase;
  /** Progress percentage (0-100) */
  planningProgress: number;

  // === Common State ===
  isGenerating: boolean;
  /** Whether the plan has been finalized (gates Booking mode) */
  isPlanFinalized: boolean;
  /** Finalize the plan (unlock Booking mode) */
  finalizePlan: () => void;
  /** Unfinalize the plan (re-enable editing) */
  unfinalizePlan: () => void;

  // === Legacy API (for backward compatibility) ===
  /** @deprecated Use activeMode instead */
  activeView: ViewName;
  /** @deprecated Use navigateToMode instead */
  navigateTo: (view: ViewName) => boolean;
  /** @deprecated Always true in new system */
  canViewSetup: boolean;
  /** @deprecated Use planningPhase.hasDates instead */
  canViewPlan: boolean;
  /** @deprecated Use canViewBooking instead */
  canViewBook: boolean;
  /** @deprecated Use planningPhase.hasDates instead */
  hasLeftSetup: boolean;
}

/**
 * Map old three-mode ViewName to new two-mode ViewMode.
 */
function legacyToMode(view: ViewName): ViewMode {
  return view === 'book' ? 'booking' : 'planning';
}

/**
 * Map new ViewMode to legacy ViewName.
 * For backward compatibility, we map 'planning' to 'plan' when dates exist,
 * otherwise to 'setup'.
 */
function modeToLegacy(mode: ViewMode, hasDates: boolean): ViewName {
  if (mode === 'booking') return 'book';
  return hasDates ? 'plan' : 'setup';
}

/**
 * useViewNavigation
 *
 * Centralized navigation logic for the two-mode system (PLANNING + BOOKING).
 *
 * Two-Mode System:
 * - PLANNING: Evolves naturally based on user inputs
 *   - Early phase: Input gathering + specialist cards
 *   - Late phase: Day-by-day itinerary + map (when dates are set)
 * - BOOKING: Transaction mode with price comparison
 *
 * Unlock Rules:
 * - PLANNING: Always accessible (default mode)
 * - BOOKING: Unlocked when plan is finalized AND has tiles/content
 *
 * @see docs/ux_unified_architecture.md for full specification
 */
export function useViewNavigation(): UseViewNavigationReturn {
  // === Store Selectors ===
  // Store now uses two-mode system natively ('planning' | 'booking')
  const storedActiveMode = useDocumentStore((s) => s.activeView ?? 'planning');
  const setActiveView = useDocumentStore((s) => s.setActiveView);
  const tiles = useDocumentStore((s) => s.document?.tiles);
  const generation = useDocumentStore((s) => s.generation);
  const strategySections = useDocumentStore((s) => s.document?.strategy_sections);
  const planViewState = useDocumentStore((s) => s.document?.plan_view_state);
  const tripInputs = useDocumentStore((s) => s.document?.trip_inputs);
  const dayCards = useDocumentStore((s) => s.document?.day_cards);
  const isGenerating = generation?.active === true;

  // Plan finalization state
  const isPlanFinalized = useDocumentStore((s) => s.isPlanFinalized);
  const setFinalized = useDocumentStore((s) => s.setFinalized);

  // === Computed State ===
  const hasTiles = Object.keys(tiles ?? {}).length > 0;
  const hasStrategyContent = (strategySections?.length ?? 0) > 0;
  const hasItinerary = (dayCards?.length ?? 0) > 0;
  const hasDates = Boolean(tripInputs?.start_date && tripInputs?.end_date);

  // Book is accessible when in a bookable state (S2 or S3)
  const inBookableState = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
    planViewState ?? ''
  );

  // === Two-Mode System ===

  // Store now uses two-mode system natively
  const activeMode: ViewMode = storedActiveMode;

  // Planning phase tracking
  const planningPhase = useMemo<PlanningPhase>(
    () =>
      computePlanningPhase(
        tripInputs,
        hasItinerary,
        isPlanFinalized // For now, use finalization as proxy for "ready to book"
      ),
    [tripInputs, hasItinerary, isPlanFinalized]
  );

  // Progress percentage
  const planningProgress = useMemo(
    () => computePlanningProgress(planningPhase),
    [planningPhase]
  );

  // Booking mode is unlocked when:
  // 1. Plan is finalized (explicit user action)
  // 2. AND has content (tiles or bookable state)
  const canViewBooking = isPlanFinalized && (hasTiles || inBookableState);

  // Unlock state with reasons
  const unlockState = useMemo<ViewUnlockState>(
    () => ({
      planning: {
        unlocked: true, // PLANNING is always accessible
        reason: null,
      },
      booking: {
        unlocked: canViewBooking,
        reason: canViewBooking
          ? null
          : !isPlanFinalized
            ? 'Finalize your plan to unlock booking'
            : 'Generate a plan to see booking options',
      },
    }),
    [canViewBooking, isPlanFinalized]
  );

  // Navigate to a mode
  const navigateToMode = useCallback(
    (mode: ViewMode): boolean => {
      // Guard: Don't allow jumping to Booking without finalization
      if (mode === 'booking' && !canViewBooking) return false;
      // Guard: Lock Booking during active generation
      if (mode === 'booking' && isGenerating) return false;

      // Store uses two-mode system natively
      setActiveView(mode);
      return true;
    },
    [canViewBooking, isGenerating, setActiveView]
  );

  // === Legacy API (for backward compatibility) ===

  // Check if user has progressed past Setup (dates + content)
  const hasLeftSetup = hasDates && (hasTiles || hasStrategyContent || inBookableState);

  // Legacy unlock rules
  const canViewSetup = !hasDates;
  const canViewPlan = hasDates || isGenerating;
  const canViewBook = canViewBooking;

  // Legacy navigate function - converts old three-mode to new two-mode
  const navigateTo = useCallback(
    (view: ViewName): boolean => {
      // Convert legacy view to new mode
      const mode = legacyToMode(view);

      // Guard: Don't allow jumping to Booking without finalization
      if (mode === 'booking' && !canViewBook) return false;
      // Guard: Lock Booking during active generation
      if (mode === 'booking' && isGenerating) return false;

      setActiveView(mode);
      return true;
    },
    [canViewBook, isGenerating, setActiveView]
  );

  // Finalization actions
  const finalizePlan = useCallback(() => {
    setFinalized(true);
  }, [setFinalized]);

  const unfinalizePlan = useCallback(() => {
    setFinalized(false);
  }, [setFinalized]);

  return {
    // === Two-Mode System (New) ===
    activeMode,
    navigateToMode,
    canViewBooking,
    unlockState,
    planningPhase,
    planningProgress,

    // === Common State ===
    isGenerating,
    isPlanFinalized,
    finalizePlan,
    unfinalizePlan,

    // === Legacy API ===
    // Convert new mode back to legacy format for backward compatibility
    activeView: modeToLegacy(storedActiveMode, hasDates),
    navigateTo,
    canViewSetup,
    canViewPlan,
    canViewBook,
    hasLeftSetup,
  };
}

/**
 * useViewNavigationLight
 *
 * Lightweight version for components that only need nav actions + basic derived state.
 * All selectors return stable primitives (booleans, strings) — no object refs.
 * Use this in root-level components like NomadicLanding to avoid broad re-renders.
 */
export function useViewNavigationLight(): Pick<
  UseViewNavigationReturn,
  'navigateTo' | 'finalizePlan' | 'canViewPlan' | 'activeView'
> {
  const storedActiveMode = useDocumentStore((s) => s.activeView ?? 'planning');
  const hasDates = useDocumentStore((s) =>
    Boolean(s.document?.trip_inputs?.start_date && s.document?.trip_inputs?.end_date)
  );
  const isGenerating = useDocumentStore((s) => s.generation?.active === true);
  const isPlanFinalized = useDocumentStore((s) => s.isPlanFinalized);
  const hasTiles = useDocumentStore((s) => {
    const tiles = s.document?.tiles;
    if (!tiles) return false;
    for (const _ in tiles) return true; // O(1) — early-exit on first own key
    return false;
  });
  const inBookableState = useDocumentStore((s) =>
    ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
      s.document?.plan_view_state ?? ''
    )
  );
  const setActiveView = useDocumentStore((s) => s.setActiveView);
  const setFinalized = useDocumentStore((s) => s.setFinalized);

  const canViewBooking = isPlanFinalized && (hasTiles || inBookableState);
  const canViewPlan = hasDates || isGenerating;

  const activeView: ViewName = storedActiveMode === 'booking' ? 'book' : hasDates ? 'plan' : 'setup';

  const navigateTo = useCallback(
    (view: ViewName): boolean => {
      const mode = legacyToMode(view);
      if (mode === 'booking' && (!canViewBooking || isGenerating)) return false;
      setActiveView(mode);
      return true;
    },
    [canViewBooking, isGenerating, setActiveView]
  );

  const finalizePlan = useCallback(() => setFinalized(true), [setFinalized]);

  return { navigateTo, finalizePlan, canViewPlan, activeView };
}
