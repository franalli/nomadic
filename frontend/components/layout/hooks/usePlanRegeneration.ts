'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { DocumentTripInputs, PlanStatus } from '@/types/document';

/**
 * Debounce delay for plan regeneration (ms).
 * Prevents thrashing when user makes multiple rapid changes.
 */
const REGENERATION_DEBOUNCE_MS = 500;

export interface UsePlanRegenerationOptions {
  /** Current trip inputs from the form */
  tripInputs: DocumentTripInputs;
  /** Whether branches exist (plan has been generated) */
  hasBranches: boolean;
  /** Callback to trigger plan regeneration */
  onRegenerate: () => Promise<void>;
}

export interface UsePlanRegenerationReturn {
  /** Current plan status: ready, stale, or updating */
  planStatus: PlanStatus;
  /** Force reset the status to ready (e.g., after manual refresh) */
  resetStatus: () => void;
  /**
   * Signal that plan data has arrived and status should be set to 'ready'.
   * Call this from handlePlanResult when branches actually arrive.
   */
  markRegenerationComplete: () => void;
}

/**
 * Computes a hash of hard constraints that trigger full plan regeneration.
 *
 * Hard constraints: origin, destinations, dates, adults, children, budget
 * Soft constraints (hotel_settings, etc.) are not included as they can
 * be handled with partial updates.
 */
function computeConstraintHash(inputs: DocumentTripInputs): string {
  const { destinations, origin, start_date, end_date, adults, children, budget } = inputs;
  return JSON.stringify({
    destinations: destinations || [],
    origin: origin || null,
    start_date: start_date || null,
    end_date: end_date || null,
    adults: adults ?? null,
    children: children ?? null,
    budget: budget ?? null,
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
  const { tripInputs, hasBranches, onRegenerate } = options;

  const [planStatus, setPlanStatus] = useState<PlanStatus>('ready');
  const lastHashRef = useRef<string | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isRegeneratingRef = useRef(false);

  // Memoize the constraint hash
  const currentHash = useMemo(() => computeConstraintHash(tripInputs), [tripInputs]);

  // Stable regenerate callback
  // NOTE: Does NOT auto-reset to 'ready' - caller must call markRegenerationComplete()
  // when plan data actually arrives. This ensures status stays 'updating' until UI updates.
  const triggerRegenerate = useCallback(async () => {
    if (isRegeneratingRef.current) return;

    isRegeneratingRef.current = true;
    setPlanStatus('updating');

    try {
      await onRegenerate();
      // NOTE: We intentionally do NOT set planStatus to 'ready' here.
      // The caller (useBranchManager.handlePlanResult) will call markRegenerationComplete()
      // when the actual branch data arrives, ensuring UI stays in loading state until data is ready.
    } catch (error) {
      // On error, reset status to ready since regeneration failed
      isRegeneratingRef.current = false;
      setPlanStatus('ready');
      throw error;
    }
  }, [onRegenerate]);

  // Signal that regeneration is complete (data has arrived)
  const markRegenerationComplete = useCallback(() => {
    isRegeneratingRef.current = false;
    setPlanStatus('ready');
  }, []);

  // Watch for constraint changes
  useEffect(() => {
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
      // Mark plan as stale immediately
      setPlanStatus('stale');

      // Cancel pending regeneration
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }

      // Schedule debounced regeneration
      debounceTimerRef.current = setTimeout(() => {
        lastHashRef.current = currentHash;
        triggerRegenerate();
      }, REGENERATION_DEBOUNCE_MS);
    }

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [currentHash, hasBranches, triggerRegenerate]);

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
    resetStatus,
    markRegenerationComplete,
  };
}
