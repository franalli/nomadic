/**
 * useItineraryRegeneration
 *
 * Auto-regenerates itinerary when user preferences change.
 * No manual Update button - full auto-reactivity with debounce.
 *
 * @see docs/ux_unified_architecture.md - Regeneration Flow
 */

'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';

import { useDocumentStore } from '@/state/documentStore';

/** Debounce delay before triggering regeneration (ms) */
const AUTO_REGEN_DEBOUNCE_MS = 2000;

/**
 * Stable JSON stringification for consistent hashing.
 * Ensures objects with different key orders produce the same hash.
 */
function stableStringify(obj: unknown): string {
  if (obj === null || obj === undefined) return '';
  if (typeof obj !== 'object') return String(obj);
  if (Array.isArray(obj)) {
    // Sort arrays for consistent ordering
    return JSON.stringify(obj.map(stableStringify).sort());
  }
  // Sort object keys for consistent ordering
  const sortedKeys = Object.keys(obj as Record<string, unknown>).sort();
  const sortedObj: Record<string, string> = {};
  for (const key of sortedKeys) {
    sortedObj[key] = stableStringify((obj as Record<string, unknown>)[key]);
  }
  return JSON.stringify(sortedObj);
}

export interface UseItineraryRegenerationReturn {
  /** Whether regeneration is currently in progress */
  isRegenerating: boolean;
  /** Whether debounce is pending (waiting to trigger regeneration) */
  isPending: boolean;
  /** Countdown seconds until regeneration triggers */
  remainingSeconds: number;
  /** Number of current preferences */
  preferenceCount: number;
  /** Set the expand function for auto-regen to call */
  setExpandFn: (fn: (() => Promise<void>) | null) => void;
  /** Manual regeneration trigger */
  confirmRegeneration: (expandFn: () => Promise<void>) => Promise<void>;
  /** Bypass debounce and trigger regeneration immediately */
  triggerImmediateRegeneration: () => void;
}

export function useItineraryRegeneration(): UseItineraryRegenerationReturn {
  // From document store
  const dayCards = useDocumentStore((s) => s.document?.day_cards);
  const preferredTileIds = useDocumentStore((s) => s.preferredTileIds);
  const lastGeneratedPreferences = useDocumentStore((s) => s.lastGeneratedPreferences);
  const markPreferencesAsApplied = useDocumentStore((s) => s.markPreferencesAsApplied);
  const awaitPreferencePatch = useDocumentStore((s) => s.awaitPreferencePatch);
  // NEW: Track trip inputs for selective regeneration
  const tripInputs = useDocumentStore((s) => s.document?.trip_inputs);

  // Regeneration UI state from store (shared across all components using this hook)
  const isRegenerating = useDocumentStore((s) => s.isRegenerating);
  const isPending = useDocumentStore((s) => s.isPending);
  const remainingSeconds = useDocumentStore((s) => s.remainingSeconds);
  const setRegenerationState = useDocumentStore((s) => s.setRegenerationState);

  // Refs for timers and scroll position
  const expandFnRef = useRef<(() => Promise<void>) | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const scrollPositionRef = useRef<number>(0);

  // Track if this is the initial mount (skip auto-regen on first render)
  const isInitialMount = useRef(true);
  // NEW: Track last generated trip inputs hash for change detection
  const lastTripInputsHashRef = useRef<string>('');
  // Track mounted state to prevent state updates after unmount
  const isMountedRef = useRef(true);
  // RACE CONDITION FIX: Guard against double regeneration
  // Prevents both debounce timer and immediate trigger from running simultaneously
  const isExecutingRegenRef = useRef(false);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      // Cancel any pending timers
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
      }
    };
  }, []);

  // Computed: check if itinerary exists
  const hasItinerary = useMemo(() => {
    return (dayCards?.length ?? 0) > 0;
  }, [dayCards]);

  // Computed: check if preferences have changed since last generation
  const hasPreferenceChanges = useMemo(() => {
    if (preferredTileIds.size !== lastGeneratedPreferences.size) return true;
    for (const id of preferredTileIds) {
      if (!lastGeneratedPreferences.has(id)) return true;
    }
    return false;
  }, [preferredTileIds, lastGeneratedPreferences]);

  // NEW: Hash trip inputs for selective regeneration change detection
  // @see docs/plan_graph_analysis.md - Selective Regeneration Strategy
  // Uses stableStringify for consistent hashing of nested objects
  const tripInputsHash = useMemo(() => {
    if (!tripInputs) return '';

    // Type-safe access to activity_settings - may be undefined or partial
    const activitySettings = (tripInputs.activity_settings || {}) as {
      categories?: string[];
      skill_level?: string;
    };

    return JSON.stringify({
      destination: tripInputs.destination,
      start_date: tripInputs.start_date,
      end_date: tripInputs.end_date,
      adults: tripInputs.adults,
      children: tripInputs.children,
      budget: tripInputs.budget,
      origin: tripInputs.origin,
      // New fields for selective regeneration (with stable ordering)
      flight_settings: stableStringify(tripInputs.flight_settings),
      hotel_settings: stableStringify(tripInputs.hotel_settings),
      activity_categories: stableStringify(activitySettings.categories),
      activity_skill_level: activitySettings.skill_level || '',
    });
  }, [tripInputs]);

  // NEW: Check if trip inputs have changed since last generation
  const hasTripInputChanges = useMemo(() => {
    if (!lastTripInputsHashRef.current) return false; // No baseline = no change
    return tripInputsHash !== lastTripInputsHashRef.current;
  }, [tripInputsHash]);

  // Combined change detection: preferences OR trip inputs changed
  const hasChanges = useMemo(() => {
    return hasPreferenceChanges || hasTripInputChanges;
  }, [hasPreferenceChanges, hasTripInputChanges]);

  // Set the expand function (called by parent component)
  const setExpandFn = useCallback((fn: (() => Promise<void>) | null) => {
    console.log('[useItineraryRegeneration] 📌 setExpandFn called:', !!fn);
    expandFnRef.current = fn;
  }, []);

  // Auto-regeneration effect
  useEffect(() => {
    // Debug: Log all conditions
    console.log('[useItineraryRegeneration] 🔄 Effect triggered:', {
      isInitialMount: isInitialMount.current,
      hasItinerary,
      hasPreferenceChanges,
      hasTripInputChanges,
      hasChanges,
      isRegenerating,
      preferredCount: preferredTileIds.size,
    });

    // Skip on initial mount - just capture the baseline tripInputsHash
    if (isInitialMount.current) {
      isInitialMount.current = false;
      lastTripInputsHashRef.current = tripInputsHash; // Set baseline
      console.log('[useItineraryRegeneration] ⏭️ Skipping initial mount, baseline set');
      return;
    }

    // Only auto-regen if:
    // 1. Itinerary exists
    // 2. Preferences OR trip inputs have changed
    // 3. Not already regenerating
    // NOTE: Don't check expandFnRef here - it may be set after this effect runs
    // We'll check it when the debounce timer fires
    if (!hasItinerary || !hasChanges || isRegenerating) {
      console.log('[useItineraryRegeneration] ⏭️ Conditions not met, skipping');
      return;
    }

    console.log('[useItineraryRegeneration] ✅ Starting debounce timer');

    // Clear existing timers (debounce reset on rapid changes)
    if (debounceTimerRef.current) {
      console.log('[useItineraryRegeneration] 🔄 Input changed during debounce - resetting timer');
      clearTimeout(debounceTimerRef.current);
    }
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
    }

    // Start pending state + countdown
    if (isMountedRef.current) {
      setRegenerationState({ isPending: true, remainingSeconds: Math.ceil(AUTO_REGEN_DEBOUNCE_MS / 1000) });
    }

    // Countdown timer (updates every second)
    countdownTimerRef.current = setInterval(() => {
      if (isMountedRef.current) {
        const current = useDocumentStore.getState().remainingSeconds;
        const next = current - 1;
        if (next <= 0 && countdownTimerRef.current) {
          clearInterval(countdownTimerRef.current);
          countdownTimerRef.current = null;
        }
        setRegenerationState({ remainingSeconds: Math.max(0, next) });
      }
    }, 1000);

    // Debounce regeneration to prevent thrashing on rapid preference changes
    debounceTimerRef.current = setTimeout(async () => {
      console.log('[useItineraryRegeneration] ⏰ Debounce timer fired, calling expand');

      // RACE CONDITION GUARD: Check if another regeneration is already executing
      // This can happen if triggerImmediateRegeneration was called right as this timer fired
      if (isExecutingRegenRef.current) {
        console.log('[useItineraryRegeneration] ⏭️ Skipping - regeneration already in progress (race avoided)');
        if (isMountedRef.current) {
          setRegenerationState({ isPending: false, remainingSeconds: 0 });
        }
        return;
      }

      // Clear countdown timer
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
        countdownTimerRef.current = null;
      }

      if (!expandFnRef.current) {
        console.log('[useItineraryRegeneration] ❌ No expandFn available');
        if (isMountedRef.current) {
          setRegenerationState({ isPending: false, remainingSeconds: 0 });
        }
        return;
      }

      // Set execution guard BEFORE any async work
      isExecutingRegenRef.current = true;

      // Save scroll position
      scrollPositionRef.current = window.scrollY;

      if (isMountedRef.current) {
        setRegenerationState({ isPending: false, remainingSeconds: 0, isRegenerating: true });
      }
      try {
        // Wait for any pending preference PATCH to complete before regen
        // This ensures the backend has the latest preferences
        await awaitPreferencePatch();
        await expandFnRef.current();
        if (isMountedRef.current) {
          markPreferencesAsApplied();
          // NEW: Track trip inputs hash for selective regeneration
          lastTripInputsHashRef.current = tripInputsHash;
          console.log('[useItineraryRegeneration] ✅ Regeneration complete');
        }
      } finally {
        // Clear execution guard
        isExecutingRegenRef.current = false;
        if (isMountedRef.current) {
          setRegenerationState({ isRegenerating: false });
          // Restore scroll position
          window.scrollTo({ top: scrollPositionRef.current, behavior: 'smooth' });
        }
      }
    }, AUTO_REGEN_DEBOUNCE_MS);

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      if (countdownTimerRef.current) {
        clearInterval(countdownTimerRef.current);
      }
    };
    // hasChanges already captures hasPreferenceChanges and hasTripInputChanges
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferredTileIds, tripInputsHash, hasItinerary, hasChanges, isRegenerating, markPreferencesAsApplied, awaitPreferencePatch]);

  // Manual regeneration trigger
  const confirmRegeneration = useCallback(
    async (expandFn: () => Promise<void>) => {
      // RACE CONDITION GUARD: Prevent concurrent regenerations
      if (isExecutingRegenRef.current) {
        console.log('[useItineraryRegeneration] ⏭️ confirmRegeneration skipped - already executing');
        return;
      }
      isExecutingRegenRef.current = true;

      scrollPositionRef.current = window.scrollY;
      setRegenerationState({ isRegenerating: true });
      try {
        // Wait for any pending preference PATCH to complete before regen
        await awaitPreferencePatch();
        await expandFn();
        if (isMountedRef.current) {
          markPreferencesAsApplied();
          // NEW: Track trip inputs hash for selective regeneration
          lastTripInputsHashRef.current = tripInputsHash;
        }
      } finally {
        // Clear execution guard
        isExecutingRegenRef.current = false;
        if (isMountedRef.current) {
          setRegenerationState({ isRegenerating: false });
          window.scrollTo({ top: scrollPositionRef.current, behavior: 'smooth' });
        }
      }
    },
    [awaitPreferencePatch, markPreferencesAsApplied, tripInputsHash, setRegenerationState]
  );

  // Bypass debounce and trigger regeneration immediately
  const triggerImmediateRegeneration = useCallback(() => {
    console.log('[useItineraryRegeneration] ⚡ Immediate bypass triggered');

    // RACE CONDITION GUARD: Check if regeneration is already executing
    // This prevents double regeneration if debounce timer callback already started
    if (isExecutingRegenRef.current) {
      console.log('[useItineraryRegeneration] ⏭️ Skipping immediate - regeneration already in progress');
      return;
    }

    // Cancel debounce + countdown timers
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }

    // Reset pending state
    if (isMountedRef.current) {
      setRegenerationState({ isPending: false, remainingSeconds: 0 });
    }

    // Execute immediately if expand function is available
    if (expandFnRef.current) {
      // Use confirmRegeneration to handle the actual regeneration
      confirmRegeneration(expandFnRef.current);
    } else {
      console.log('[useItineraryRegeneration] ❌ No expandFn available for immediate trigger');
    }
  }, [confirmRegeneration, setRegenerationState]);

  return {
    isRegenerating,
    isPending,
    remainingSeconds,
    preferenceCount: preferredTileIds.size,
    setExpandFn,
    confirmRegeneration,
    triggerImmediateRegeneration,
  };
}
