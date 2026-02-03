/**
 * useManualRegeneration
 *
 * Tracks trip input changes and provides a manual regeneration trigger.
 * When Refresh is clicked, it triggers a FULL plan regeneration via the chat system.
 * This ensures tiles are re-fetched from APIs (not cached) when destination/settings change.
 *
 * @see docs/ux_unified_architecture.md - Regeneration Flow
 */

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';

/** Minimum overlay duration to prevent jarring flash (ms) */
const MIN_OVERLAY_DURATION_MS = 600;

/**
 * Compute a stable hash of trip inputs for change detection.
 * Only includes fields that trigger regeneration when changed.
 */
function computeTripInputsHash(inputs: DocumentTripInputs | null | undefined): string {
  if (!inputs) {
    return '';
  }

  return JSON.stringify({
    // Core trip inputs
    d: inputs.destination || null,
    dt: [inputs.start_date || null, inputs.end_date || null],
    o: inputs.origin || null,
    // Hotel settings that affect tile selection
    hotel_stars: inputs.hotel_settings?.min_stars || null,
    hotel_amenities: [...(inputs.hotel_settings?.amenities || [])].sort(),
    // Flight settings
    flight_cabin: inputs.flight_settings?.cabin_class || null,
    flight_direct: inputs.flight_settings?.direct_only || null,
    // Activity settings
    activity_categories: [...(inputs.activity_settings?.categories || [])].sort(),
    activity_skill: inputs.activity_settings?.skill_level || null,
  });
}

export interface UseManualRegenerationOptions {
  /**
   * Callback to trigger full plan regeneration via chat system.
   * Should send GENERATE_PLAN_TRIGGER to chatPanelRef.
   */
  onFullRegenerate?: () => void;
  /**
   * Callback to run after plan regeneration completes.
   * Use this to auto-trigger itinerary generation.
   */
  onAfterRegenerate?: () => void;
  /**
   * Callback when regeneration fails. Use to show error toast.
   */
  onError?: (error: Error) => void;
}

export interface UseManualRegenerationReturn {
  /** Whether trip inputs have changed since last regeneration */
  hasChanges: boolean;
  /** Whether regeneration is currently in progress */
  isRefreshing: boolean;
  /** Trigger manual regeneration */
  regenerate: () => Promise<void>;
  /** Mark current inputs as validated (e.g., after initial generation) */
  markValidated: () => void;
  /** Reset internal state (call when starting a fresh trip) */
  resetState: () => void;
}

export function useManualRegeneration(
  options: UseManualRegenerationOptions = {}
): UseManualRegenerationReturn {
  const { onFullRegenerate, onAfterRegenerate, onError } = options;

  // State from document store
  const tripInputs = useDocumentStore((s) => s.document?.trip_inputs);

  // Local state for overlay
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Ref-based guard for synchronous lock check (avoids stale closure)
  const isRefreshingRef = useRef(false);

  // Track last validated hash
  const lastValidatedHashRef = useRef<string>('');
  const isInitializedRef = useRef(false);

  // Compute current hash
  const currentHash = useMemo(() => computeTripInputsHash(tripInputs), [tripInputs]);

  // Initialize hash on first valid inputs
  useEffect(() => {
    if (currentHash && !isInitializedRef.current) {
      lastValidatedHashRef.current = currentHash;
      isInitializedRef.current = true;
    }
  }, [currentHash]);

  // Check if inputs have changed since last validation
  const hasChanges = useMemo(() => {
    // No changes if not initialized yet
    if (!isInitializedRef.current) return false;
    // No changes if currently refreshing (button should be disabled)
    if (isRefreshing) return false;
    return currentHash !== lastValidatedHashRef.current;
  }, [currentHash, isRefreshing]);

  // Mark current inputs as validated (call after successful generation)
  const markValidated = useCallback(() => {
    lastValidatedHashRef.current = currentHash;
  }, [currentHash]);

  // Reset internal state (call when starting a fresh trip)
  const resetState = useCallback(() => {
    lastValidatedHashRef.current = '';
    isInitializedRef.current = false;
    isRefreshingRef.current = false;
    setIsRefreshing(false);
  }, []);

  // Regenerate function - triggers full plan regeneration
  const regenerate = useCallback(async () => {
    // Ref-based guard for synchronous check (avoids stale closure)
    if (isRefreshingRef.current) return;

    // RACE GUARD: Also check store's isRegenerating (usePreferenceAutoRegen might be running)
    if (useDocumentStore.getState().isRegenerating) return;

    // Set both ref and state
    isRefreshingRef.current = true;
    setIsRefreshing(true);

    // COORDINATION: Also set store's isRegenerating so usePreferenceAutoRegen won't start
    useDocumentStore.getState().setRegenerationState({ isRegenerating: true });

    const startTime = Date.now();

    // Capture initial document state to detect changes
    const initialTileCount = Object.keys(useDocumentStore.getState().document?.tiles ?? {}).length;
    const initialPlanViewState = useDocumentStore.getState().document?.plan_view_state;
    const initialDestination = useDocumentStore.getState().document?.trip_inputs?.destination;

    // Safety timeout to prevent permanent lock if regeneration hangs
    const MAX_REGEN_TIME_MS = 45000;
    const safetyTimeout = setTimeout(() => {
      if (isRefreshingRef.current) {
        console.warn('[useManualRegeneration] Safety timeout - forcing unlock after 45s');
        isRefreshingRef.current = false;
        setIsRefreshing(false);
        useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
      }
    }, MAX_REGEN_TIME_MS);

    try {
      // Trigger full plan regeneration via chat system
      // This runs the full graph: ROUTER -> SPECIALIST -> LOGISTICS -> ARCHITECT -> SYNTH
      // LOGISTICS will fetch fresh tiles based on current settings
      if (onFullRegenerate) {
        onFullRegenerate();

        // Wait for the document to change (tiles updated or plan_view_state changed)
        // This indicates the graph has completed and new data is available
        await new Promise<void>((resolve) => {
          const checkInterval = setInterval(() => {
            const doc = useDocumentStore.getState().document;
            const currentTileCount = Object.keys(doc?.tiles ?? {}).length;
            const currentPlanViewState = doc?.plan_view_state;
            const currentDestination = doc?.trip_inputs?.destination;

            // Document has changed - regeneration complete
            const tileCountChanged = currentTileCount !== initialTileCount;
            const planViewStateChanged = currentPlanViewState !== initialPlanViewState;
            const destinationChanged = currentDestination !== initialDestination;

            if (tileCountChanged || planViewStateChanged || destinationChanged) {
              clearInterval(checkInterval);
              resolve();
            }
          }, 200);

          // Safety timeout - resolve after 30 seconds regardless
          setTimeout(() => {
            clearInterval(checkInterval);
            resolve();
          }, 30000);
        });
      }

      // Success - mark validated with new hash (computed from current state)
      const newTripInputs = useDocumentStore.getState().document?.trip_inputs;
      const newHash = computeTripInputsHash(newTripInputs);
      lastValidatedHashRef.current = newHash;
      useDocumentStore.getState().markPreferencesAsApplied();

      // CRITICAL: Reset flags BEFORE calling onAfterRegenerate
      // so handleExpandToItinerary doesn't hit GATE 0 (isRegenerating check)
      isRefreshingRef.current = false;
      setIsRefreshing(false);
      useDocumentStore.getState().setRegenerationState({ isRegenerating: false });

      // Auto-trigger itinerary generation after plan refresh
      if (onAfterRegenerate) {
        onAfterRegenerate();
      }
    } catch (error) {
      console.error('[useManualRegeneration] Regeneration failed:', error);
      // Call error handler if provided
      if (onError) {
        onError(error instanceof Error ? error : new Error(String(error)));
      }
      // Don't update lastValidatedHashRef - keep button enabled for retry
    } finally {
      // Clear safety timeout (regeneration completed normally)
      clearTimeout(safetyTimeout);

      // Enforce minimum overlay duration
      const elapsed = Date.now() - startTime;
      if (elapsed < MIN_OVERLAY_DURATION_MS) {
        await new Promise((r) => setTimeout(r, MIN_OVERLAY_DURATION_MS - elapsed));
      }

      // Reset both ref and state
      isRefreshingRef.current = false;
      setIsRefreshing(false);

      // COORDINATION: Also reset store's isRegenerating
      useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
    }
  }, [onFullRegenerate, onAfterRegenerate, onError]);

  // Memoize return object to prevent consumers from re-rendering when values haven't changed
  return useMemo(
    () => ({
      hasChanges,
      isRefreshing,
      regenerate,
      markValidated,
      resetState,
    }),
    [hasChanges, isRefreshing, regenerate, markValidated, resetState]
  );
}
