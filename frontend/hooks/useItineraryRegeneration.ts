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

  // Local state
  const [isRegenerating, setIsRegenerating] = useState(false);
  const expandFnRef = useRef<(() => Promise<void>) | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollPositionRef = useRef<number>(0);

  // Track if this is the initial mount (skip auto-regen on first render)
  const isInitialMount = useRef(true);

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
      isRegenerating,
      preferredCount: preferredTileIds.size,
    });

    // Skip on initial mount
    if (isInitialMount.current) {
      isInitialMount.current = false;
      console.log('[useItineraryRegeneration] ⏭️ Skipping initial mount');
      return;
    }

    // Only auto-regen if:
    // 1. Itinerary exists
    // 2. Preferences have changed
    // 3. Not already regenerating
    // NOTE: Don't check expandFnRef here - it may be set after this effect runs
    // We'll check it when the debounce timer fires
    if (!hasItinerary || !hasPreferenceChanges || isRegenerating) {
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

      setIsRegenerating(true);
      try {
        await expandFnRef.current();
        markPreferencesAsApplied();
        console.log('[useItineraryRegeneration] ✅ Regeneration complete');
      } finally {
        setIsRegenerating(false);
        // Restore scroll position
        window.scrollTo({ top: scrollPositionRef.current, behavior: 'smooth' });
      }
    }, AUTO_REGEN_DEBOUNCE_MS);

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [preferredTileIds, hasItinerary, hasPreferenceChanges, isRegenerating, markPreferencesAsApplied]);

  // Manual regeneration trigger
  const confirmRegeneration = useCallback(
    async (expandFn: () => Promise<void>) => {
      scrollPositionRef.current = window.scrollY;
      setIsRegenerating(true);
      try {
        await expandFn();
        markPreferencesAsApplied();
      } finally {
        setIsRegenerating(false);
        window.scrollTo({ top: scrollPositionRef.current, behavior: 'smooth' });
      }
    },
    [markPreferencesAsApplied]
  );

  return {
    isRegenerating,
    preferenceCount: preferredTileIds.size,
    setExpandFn,
    confirmRegeneration,
  };
}
