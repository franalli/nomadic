'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { useCallback } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { BOOKABLE_STATES } from '@/components/plan/planStateHelpers';
import { useDocumentStore } from '@/state/documentStore';
import {
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
  // Actions (stable refs — never trigger rerenders)
  const { setActiveView, setFinalized } = useDocumentStore(
    useShallow((s) => ({ setActiveView: s.setActiveView, setFinalized: s.setFinalized }))
  );

  // Derived booleans (all primitives — useShallow comparison is cheap)
  const { storedActiveMode, hasDates, isGenerating, isPlanFinalized, hasTiles, inBookableState } =
    useDocumentStore(
      useShallow((s) => ({
        storedActiveMode: s.activeView ?? 'planning',
        hasDates: Boolean(s.document?.trip_inputs?.start_date && s.document?.trip_inputs?.end_date),
        isGenerating: s.generation?.active === true,
        isPlanFinalized: s.isPlanFinalized,
        hasTiles: (() => {
          const t = s.document?.tiles;
          if (!t) return false;
          for (const _ in t) return true;
          return false;
        })(),
        inBookableState: BOOKABLE_STATES.has(s.document?.plan_view_state ?? ''),
      }))
    );

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
