import { useCallback, useMemo } from 'react';

import { useDocumentStore } from '@/state/documentStore';

export type ViewName = 'setup' | 'plan' | 'book';

export interface ViewUnlockState {
  setup: { unlocked: boolean; reason: string | null };
  plan: { unlocked: boolean; reason: string | null };
  book: { unlocked: boolean; reason: string | null };
}

export interface UseViewNavigationReturn {
  activeView: ViewName;
  navigateTo: (view: ViewName) => boolean;
  canViewSetup: boolean;
  canViewPlan: boolean;
  canViewBook: boolean;
  unlockState: ViewUnlockState;
  isGenerating: boolean;
  /** Whether user has progressed past Setup (plan generation has started) */
  hasLeftSetup: boolean;
  /** Whether the plan has been finalized (gates Book view) */
  isPlanFinalized: boolean;
  /** Finalize the plan (unlock Book view) */
  finalizePlan: () => void;
  /** Unfinalize the plan (re-enable editing, requires re-finalization) */
  unfinalizePlan: () => void;
}

/**
 * useViewNavigation
 *
 * Centralized navigation logic for view switching with unlock rules.
 * Decouples "which view is shown" from "plan progress state" (S0/S1/S2/S3).
 *
 * Navigation Flow:
 * - Setup → Plan → Book (forward progression)
 * - Plan ↔ Book (bidirectional)
 * - NO going back to Setup once plan generation has started
 *
 * Unlock Rules:
 * - Setup: Only accessible before plan generation starts
 * - Plan: Unlocked when Build is clicked (generation starts or content exists)
 * - Book: Unlocked when tiles exist OR in bookable state (S2+)
 */
export function useViewNavigation(): UseViewNavigationReturn {
  const activeView = useDocumentStore((s) => s.activeView ?? 'setup');
  const setActiveView = useDocumentStore((s) => s.setActiveView);
  const tiles = useDocumentStore((s) => s.document?.tiles);
  const generation = useDocumentStore((s) => s.document?.generation);
  const strategySections = useDocumentStore((s) => s.document?.strategy_sections);
  const planViewState = useDocumentStore((s) => s.document?.plan_view_state);
  const tripInputs = useDocumentStore((s) => s.document?.trip_inputs);
  const isGenerating = generation?.active === true;

  // Plan finalization state
  const isPlanFinalized = useDocumentStore((s) => s.isPlanFinalized);
  const setFinalized = useDocumentStore((s) => s.setFinalized);

  // Check tile availability
  const hasTiles = Object.keys(tiles ?? {}).length > 0;
  const hasStrategyContent = (strategySections?.length ?? 0) > 0;

  // CRITICAL: Dates are the gatekeeper for Plan navigation
  // @see docs/ux_unified_architecture.md Section VI - "Dates are the Gatekeeper"
  const hasDates = Boolean(tripInputs?.start_date);

  // Book is accessible when in a bookable state (S2 or S3)
  const inBookableState = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(planViewState ?? '');

  // Check if user has progressed past Setup (requires BOTH dates AND content)
  // Strategy content alone is Bridge Mode (still in Setup conceptually)
  // Only when dates are set do we truly "leave Setup"
  const hasLeftSetup = hasDates && (hasTiles || hasStrategyContent || inBookableState);

  // Unlock Rules (Grand Unification - dates are the gatekeeper)
  // Setup: Only accessible if we haven't set dates yet
  const canViewSetup = !hasDates;
  // Plan: Unlocked when dates are set (enables logistics/pricing)
  const canViewPlan = hasDates || isGenerating;
  // Book: Unlocked when plan is finalized AND (tiles exist OR in bookable state)
  const canViewBook = isPlanFinalized && (hasTiles || inBookableState);

  // Compute unlock state with reasons for UI feedback
  const unlockState = useMemo<ViewUnlockState>(
    () => ({
      setup: {
        unlocked: canViewSetup,
        reason: canViewSetup ? null : 'Cannot go back to Setup after planning has started',
      },
      plan: {
        unlocked: canViewPlan,
        reason: canViewPlan ? null : 'Click Build to generate your plan',
      },
      book: {
        unlocked: canViewBook,
        reason: canViewBook
          ? null
          : !isPlanFinalized
            ? 'Finalize your plan to unlock booking'
            : 'Generate a plan to see booking options',
      },
    }),
    [canViewSetup, canViewPlan, canViewBook]
  );

  const navigateTo = useCallback(
    (view: ViewName): boolean => {
      // Guard: Don't allow going back to Setup after plan generation
      if (view === 'setup' && hasLeftSetup) return false;
      // Guard: Don't allow jumping to Plan until Build is clicked
      if (view === 'plan' && !canViewPlan) return false;
      // Guard: Don't allow jumping to Book without finalization
      if (view === 'book' && !canViewBook) return false;
      // Guard: Lock Book during active generation to prevent stale data display
      if (view === 'book' && isGenerating) return false;

      setActiveView(view);
      return true;
    },
    [hasLeftSetup, canViewPlan, canViewBook, isGenerating, setActiveView]
  );

  // Finalization actions
  const finalizePlan = useCallback(() => {
    setFinalized(true);
  }, [setFinalized]);

  const unfinalizePlan = useCallback(() => {
    setFinalized(false);
  }, [setFinalized]);

  return {
    activeView,
    navigateTo,
    canViewSetup,
    canViewPlan,
    canViewBook,
    unlockState,
    isGenerating,
    hasLeftSetup,
    isPlanFinalized,
    finalizePlan,
    unfinalizePlan,
  };
}
