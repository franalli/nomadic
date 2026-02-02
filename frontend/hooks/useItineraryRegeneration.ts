/**
 * useItineraryRegeneration
 *
 * Auto-regenerates itinerary when user preferences change.
 * No manual Update button - full auto-reactivity with debounce.
 *
 * @see docs/ux_unified_architecture.md - Regeneration Flow
 */

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useDocumentStore } from '@/state/documentStore';

/** Debounce delay before triggering regeneration (ms) */
const AUTO_REGEN_DEBOUNCE_MS = 1500;

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
  /** Number of current preferences */
  preferenceCount: number;
  /** Set the expand function for auto-regen to call */
  setExpandFn: (fn: (() => Promise<void>) | null) => void;
  /** Manual regeneration trigger */
  confirmRegeneration: (expandFn: () => Promise<void>) => Promise<void>;
}

export function useItineraryRegeneration(): UseItineraryRegenerationReturn {
  // From document store
  const dayCards = useDocumentStore((s) => s.document?.day_cards);
  const preferredTileIds = useDocumentStore((s) => s.preferredTileIds);
  const lastGeneratedPreferences = useDocumentStore((s) => s.lastGeneratedPreferences);
  const markPreferencesAsApplied = useDocumentStore((s) => s.markPreferencesAsApplied);
  // NEW: Track trip inputs for selective regeneration
  const tripInputs = useDocumentStore((s) => s.document?.trip_inputs);

  // Local state
  const [isRegenerating, setIsRegenerating] = useState(false);
  const expandFnRef = useRef<(() => Promise<void>) | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollPositionRef = useRef<number>(0);

  // Track if this is the initial mount (skip auto-regen on first render)
  const isInitialMount = useRef(true);
  // NEW: Track last generated trip inputs hash for change detection
  const lastTripInputsHashRef = useRef<string>('');
  // Track mounted state to prevent state updates after unmount
  const isMountedRef = useRef(true);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      // Cancel any pending debounce timer
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
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

    // Clear existing timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    // Debounce regeneration to prevent thrashing on rapid preference changes
    debounceTimerRef.current = setTimeout(async () => {
      console.log('[useItineraryRegeneration] ⏰ Debounce timer fired, calling expand');
      if (!expandFnRef.current) {
        console.log('[useItineraryRegeneration] ❌ No expandFn available');
        return;
      }

      // Save scroll position
      scrollPositionRef.current = window.scrollY;

      if (isMountedRef.current) setIsRegenerating(true);
      try {
        await expandFnRef.current();
        if (isMountedRef.current) {
          markPreferencesAsApplied();
          // NEW: Track trip inputs hash for selective regeneration
          lastTripInputsHashRef.current = tripInputsHash;
          console.log('[useItineraryRegeneration] ✅ Regeneration complete');
        }
      } finally {
        if (isMountedRef.current) {
          setIsRegenerating(false);
          // Restore scroll position
          window.scrollTo({ top: scrollPositionRef.current, behavior: 'smooth' });
        }
      }
    }, AUTO_REGEN_DEBOUNCE_MS);

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
    // hasChanges already captures hasPreferenceChanges and hasTripInputChanges
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferredTileIds, tripInputsHash, hasItinerary, hasChanges, isRegenerating, markPreferencesAsApplied]);

  // Manual regeneration trigger
  const confirmRegeneration = useCallback(
    async (expandFn: () => Promise<void>) => {
      scrollPositionRef.current = window.scrollY;
      setIsRegenerating(true);
      try {
        await expandFn();
        if (isMountedRef.current) {
          markPreferencesAsApplied();
          // NEW: Track trip inputs hash for selective regeneration
          lastTripInputsHashRef.current = tripInputsHash;
        }
      } finally {
        if (isMountedRef.current) {
          setIsRegenerating(false);
          window.scrollTo({ top: scrollPositionRef.current, behavior: 'smooth' });
        }
      }
    },
    [markPreferencesAsApplied, tripInputsHash]
  );

  return {
    isRegenerating,
    preferenceCount: preferredTileIds.size,
    setExpandFn,
    confirmRegeneration,
  };
}
