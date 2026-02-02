'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDocumentStore, useDocumentTripInputs } from '@/state/documentStore';
import type { DocumentTripInputs, PlanStatus } from '@/types/document';

/**
 * Debounce delay for plan regeneration (ms).
 * Aligned with useItineraryRegeneration for consistent UX.
 * @see docs/plan_graph_analysis.md - Debounce with Visual Feedback
 */
const REGENERATION_DEBOUNCE_MS = 2000;

/**
 * Identifies what triggered a regeneration.
 * Used to determine how to handle chat display.
 *
 * - `auto_on_submit`: User submitted a message (show user bubble, no "Generate plan")
 * - `auto_on_change`: Constraint changed via UI (silent - no chat messages)
 * - `manual_cta`: User clicked a manual CTA button (optional system-line)
 */
export type RegenCause = 'auto_on_submit' | 'auto_on_change' | 'manual_cta';

export interface UsePlanRegenerationOptions {
  /** Current trip inputs from the form */
  tripInputs: DocumentTripInputs;
  /** Whether branches exist (plan has been generated) */
  hasBranches: boolean;
  /** Callback to trigger plan regeneration (receives the cause) */
  onRegenerate: (cause: RegenCause) => Promise<void>;
}

export interface UsePlanRegenerationReturn {
  /** Current plan status: ready, stale, or updating */
  planStatus: PlanStatus;
  /** Whether a regeneration is currently in-flight */
  isRegenerating: boolean;
  /** Force reset the status to ready (e.g., after manual refresh) */
  resetStatus: () => void;
  /**
   * Signal that plan data has arrived and status should be set to 'ready'.
   * Call this from handlePlanResult when branches actually arrive.
   */
  markRegenerationComplete: () => void;
}

/**
 * Computes a hash of constraints that trigger full plan regeneration.
 *
 * Hard constraints: origin, destination, dates, adults, children, budget
 * Activity constraints: activity_settings.categories (triggers specialist re-orchestration)
 *
 * Arrays are sorted before hashing to ensure stable comparison regardless of order.
 */
function computeConstraintHash(inputs: DocumentTripInputs): string {
  const {
    destination,
    origin,
    start_date,
    end_date,
    adults,
    children,
    budget,
    activity_settings,
  } = inputs;

  // Sort arrays for stable hashing (prevents spurious regenerations from order changes)
  const sortedCategories = [...(activity_settings?.categories || [])].sort();

  return JSON.stringify({
    destination: destination || null,
    origin: origin || null,
    start_date: start_date || null,
    end_date: end_date || null,
    adults: adults ?? null,
    children: children ?? null,
    budget: budget ?? null,
    activity_categories: sortedCategories,
  });
}

/**
 * Hook for reactive plan regeneration when constraints change.
 *
 * Implements the principle: "Constraints are live, plans are derived."
 *
 * When hard constraints change after plan generation:
 * 1. Plan is immediately marked as 'stale'
 * 2. Regeneration is debounced (500ms) to batch rapid changes
 * 3. Status transitions: ready → stale → updating → ready
 *
 * Visual feedback is mandatory - the UI must show plan status.
 */
export function usePlanRegeneration(
  options: UsePlanRegenerationOptions
): UsePlanRegenerationReturn {
  const { tripInputs: propTripInputs, hasBranches, onRegenerate } = options;

  // CRITICAL: Subscribe directly to store for live updates
  // Props may be stale due to prop-drilling, but store is always fresh after PATCH
  const storeTripInputs = useDocumentTripInputs();
  const tripInputs = storeTripInputs ?? propTripInputs;

  const [planStatus, setPlanStatus] = useState<PlanStatus>('ready');
  const [isRegenerating, setIsRegenerating] = useState(false);
  const lastHashRef = useRef<string | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Use shared regeneration state from documentStore for visual feedback
  const setRegenerationState = useDocumentStore((s) => s.setRegenerationState);

  // Memoize the constraint hash - now uses store-based tripInputs
  // Returns empty string if no inputs yet (prevents regeneration before plan exists)
  const currentHash = useMemo(
    () => (tripInputs ? computeConstraintHash(tripInputs) : ''),
    [tripInputs]
  );

  // Stable regenerate callback
  // NOTE: Does NOT auto-reset to 'ready' - caller must call markRegenerationComplete()
  // when plan data actually arrives. This ensures status stays 'updating' until UI updates.
  const triggerRegenerate = useCallback(async (cause: RegenCause) => {
    if (isRegenerating) return;

    setIsRegenerating(true);
    setPlanStatus('updating');
    // Set shared regeneration state for visual feedback
    setRegenerationState({ isRegenerating: true, isPending: false, remainingSeconds: 0 });

    try {
      await onRegenerate(cause);
      // NOTE: We intentionally do NOT set planStatus to 'ready' here.
      // The caller (useBranchManager.handlePlanResult) will call markRegenerationComplete()
      // when the actual branch data arrives, ensuring UI stays in loading state until data is ready.
    } catch (error) {
      // On error, reset status to ready since regeneration failed
      setIsRegenerating(false);
      setPlanStatus('ready');
      setRegenerationState({ isRegenerating: false });
      throw error;
    }
  }, [isRegenerating, onRegenerate, setRegenerationState]);

  // Signal that regeneration is complete (data has arrived)
  const markRegenerationComplete = useCallback(() => {
    setIsRegenerating(false);
    setPlanStatus('ready');
    // Also clear the shared regeneration state
    setRegenerationState({ isRegenerating: false, isPending: false, remainingSeconds: 0 });
  }, [setRegenerationState]);

  // Watch for constraint changes
  useEffect(() => {
    // Skip if no hash yet (no inputs)
    if (!currentHash) {
      return;
    }

    // Skip if no branches yet (first generate hasn't happened)
    if (!hasBranches) {
      lastHashRef.current = currentHash;
      return;
    }

    // Skip if this is the first hash capture after branches exist
    if (lastHashRef.current === null) {
      lastHashRef.current = currentHash;
      return;
    }

    // Check if hard constraints changed
    if (currentHash !== lastHashRef.current) {
      // DEBUG: Log hash change detection
      console.log('[usePlanRegeneration] Constraint hash changed!');
      console.log('[usePlanRegeneration]   old:', lastHashRef.current?.slice(0, 50) + '...');
      console.log('[usePlanRegeneration]   new:', currentHash.slice(0, 50) + '...');
      console.log('[usePlanRegeneration]   dates:', tripInputs?.start_date, 'to', tripInputs?.end_date);

      // Mark plan as stale immediately
      setPlanStatus('stale');

      // Cancel pending regeneration and countdown
      if (debounceTimerRef.current) {
        console.log('[usePlanRegeneration] 🔄 Constraint changed during debounce - resetting timer');
        clearTimeout(debounceTimerRef.current);
      }
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
      }

      // Start visual feedback (shared with useItineraryRegeneration via documentStore)
      setRegenerationState({
        isPending: true,
        remainingSeconds: Math.ceil(REGENERATION_DEBOUNCE_MS / 1000),
      });

      // Countdown timer (updates every second)
      countdownTimerRef.current = setInterval(() => {
        const current = useDocumentStore.getState().remainingSeconds;
        const next = current - 1;
        if (next <= 0 && countdownTimerRef.current) {
          clearInterval(countdownTimerRef.current);
          countdownTimerRef.current = null;
        }
        setRegenerationState({ remainingSeconds: Math.max(0, next) });
      }, 1000);

      // Schedule debounced regeneration (auto_on_change - constraint UI changes)
      debounceTimerRef.current = setTimeout(() => {
        console.log('[usePlanRegeneration] Triggering regeneration after debounce');

        // Clear countdown timer
        if (countdownTimerRef.current) {
          clearInterval(countdownTimerRef.current);
          countdownTimerRef.current = null;
        }

        // Reset pending state, set regenerating
        setRegenerationState({ isPending: false, remainingSeconds: 0 });

        lastHashRef.current = currentHash;
        triggerRegenerate('auto_on_change');
      }, REGENERATION_DEBOUNCE_MS);
    }

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
      }
    };
  }, [currentHash, hasBranches, triggerRegenerate, tripInputs?.start_date, tripInputs?.end_date, setRegenerationState]);

  // Reset status (e.g., when manually refreshing)
  const resetStatus = useCallback(() => {
    lastHashRef.current = currentHash;
    setPlanStatus('ready');
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
  }, [currentHash]);

  return {
    planStatus,
    isRegenerating,
    resetStatus,
    markRegenerationComplete,
  };
}
