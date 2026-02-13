/**
 * usePreferenceAutoRegen
 *
 * Automatically regenerates itinerary when user preferences (hearts) change.
 * Debounced (1.5s) to batch rapid heart toggles into a single expand call.
 *
 * @see docs/ux_unified_architecture.md - Heart Preference System
 */

'use client';

import { useCallback, useEffect, useRef } from 'react';

import { apiFetch } from '@/lib/api';
import { useDocumentStore } from '@/state/documentStore';

export interface UsePreferenceAutoRegenReturn {
  /** Whether auto-regen is currently in progress */
  isRegenerating: boolean;
  /** ID of the tile that was just hearted (for inline spinner feedback) */
  justHeartedId: string | null;
}

/**
 * Compare two sets for equality.
 */
function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) {
    if (!b.has(id)) return false;
  }
  return true;
}

export function usePreferenceAutoRegen(): UsePreferenceAutoRegenReturn {
  // State from document store
  const preferredTileIds = useDocumentStore((s) => s.preferredTileIds);
  const lastGeneratedPreferences = useDocumentStore((s) => s.lastGeneratedPreferences);
  const dayCards = useDocumentStore((s) => s.document?.day_cards);
  const isRegenerating = useDocumentStore((s) => s.isRegenerating);
  const expandInProgress = useDocumentStore((s) => s.expandInProgress);
  const setRegenerationState = useDocumentStore((s) => s.setRegenerationState);
  const awaitPreferencePatch = useDocumentStore((s) => s.awaitPreferencePatch);
  const markPreferencesAsApplied = useDocumentStore((s) => s.markPreferencesAsApplied);
  // Gate: defer fill-day during active plan generation (prevents noise during Q&A)
  const isStreamingResponse = useDocumentStore((s) => s.currentRunId !== null);

  // Track the tile that was just hearted (for UI feedback)
  const justHeartedIdRef = useRef<string | null>(null);

  // Abort in-flight regen when a new one triggers or component unmounts
  const abortRef = useRef<AbortController | null>(null);

  // Debounce timer for batching rapid heart toggles
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track if this is the initial mount
  const isInitialMount = useRef(true);

  // Track last known preferences to detect which tile changed
  const lastPrefsRef = useRef<Set<string>>(new Set());

  // Queue regen when preference changes are detected during expandInProgress mutex
  const pendingRegenRef = useRef(false);

  // Check if itinerary exists
  const hasItinerary = (dayCards?.length ?? 0) > 0;

  // Regeneration function
  const triggerRegeneration = useCallback(async () => {
    // Race condition guards
    if (useDocumentStore.getState().isRegenerating) return;
    if (useDocumentStore.getState().expandInProgress) return;

    // Abort any in-flight regen before starting a new one
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    // Set expand-in-progress flag to prevent cascade
    useDocumentStore.getState().setExpandInProgress(true);
    setRegenerationState({ isRegenerating: true });

    try {
      // Wait for preference PATCH to complete first
      await awaitPreferencePatch();

      // Build request body
      const document = useDocumentStore.getState().document;
      const prefs = useDocumentStore.getState().preferredTileIds;

      // Separate hotel, activity, and flight preferences
      const hotelIds: string[] = [];
      const activityIds: string[] = [];
      const flightIds: string[] = [];

      if (document?.tiles) {
        for (const id of prefs) {
          const tile = document.tiles[id];
          if (tile) {
            if (tile.type === 'hotel') {
              hotelIds.push(id);
            } else if (tile.type === 'activity') {
              activityIds.push(id);
            } else if (tile.type === 'flight') {
              flightIds.push(id);
            }
          }
        }
      }

      const response = await apiFetch('/api/expand-itinerary', {
        method: 'POST',
        signal,
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          trip_inputs: document?.trip_inputs,
          strategy_sections: document?.strategy_sections,
          tiles: document?.tiles,
          preferences: {
            preferred_hotel_ids: hotelIds,
            preferred_activity_ids: activityIds,
            preferred_flight_ids: flightIds,
          },
        }),
      });

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      // Parse NDJSON streaming response
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (reader) {
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const event = JSON.parse(line);
              if (event.type === 'envelope') {
                useDocumentStore.getState().mergeEnvelope(event.plan_envelope);
              } else if (event.type === 'done') {
                // CRITICAL: Sync version from backend to prevent 409 on next PATCH
                // expand-itinerary persists changes which increments version
                if (typeof event.version === 'number') {
                  useDocumentStore.setState({ version: event.version });
                }
                // Log warning if some preferred activities couldn't fit
                if (event.dropped_preferred_count && event.dropped_preferred_count > 0) {
                  console.warn(
                    `[itinerary] ⚠️ ${event.dropped_preferred_count} preferred activities couldn't fit — not enough free days`
                  );
                }
              } else if (event.type === 'error') {
                throw new Error(event.message || 'Regeneration failed');
              }
            } catch {
              // Skip unparseable lines
            }
          }
        }
      }

      // Success - mark preferences as applied
      markPreferencesAsApplied();
    } catch (error) {
      if (signal.aborted) return; // Superseded by a newer regen — silent exit
      console.error('[usePreferenceAutoRegen] Regeneration failed:', error);
      // No toast for preference regen - it's a background operation
    } finally {
      setRegenerationState({ isRegenerating: false });
      useDocumentStore.getState().setExpandInProgress(false);
      justHeartedIdRef.current = null;
    }
  }, [awaitPreferencePatch, markPreferencesAsApplied, setRegenerationState]);

  // Abort in-flight regen and clear debounce on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Watch for preference changes
  useEffect(() => {
    // Skip initial mount
    if (isInitialMount.current) {
      isInitialMount.current = false;
      lastPrefsRef.current = new Set(preferredTileIds);
      return;
    }

    // Skip if no itinerary to regenerate
    if (!hasItinerary) {
      lastPrefsRef.current = new Set(preferredTileIds);
      return;
    }

    // Skip if expand-itinerary is already running (prevents cascade)
    // Queue for later instead of silently dropping
    if (expandInProgress || isStreamingResponse) {
      console.log('[usePreferenceAutoRegen] Queuing - expand or streaming in progress');
      pendingRegenRef.current = true;
      lastPrefsRef.current = new Set(preferredTileIds);
      return;
    }

    // Check if preferences changed from last known
    if (setsEqual(preferredTileIds, lastPrefsRef.current)) {
      return; // No change
    }

    // Find which tile was just toggled (for inline spinner)
    for (const id of preferredTileIds) {
      if (!lastPrefsRef.current.has(id)) {
        justHeartedIdRef.current = id;
        break;
      }
    }
    for (const id of lastPrefsRef.current) {
      if (!preferredTileIds.has(id)) {
        justHeartedIdRef.current = id;
        break;
      }
    }

    // Update last prefs before triggering regen
    lastPrefsRef.current = new Set(preferredTileIds);

    // Check if these preferences differ from last GENERATED preferences
    // (avoids re-triggering after regen completes and syncs)
    if (setsEqual(preferredTileIds, lastGeneratedPreferences)) {
      return;
    }

    // Debounce: batch rapid heart toggles into a single regen (1.5s window)
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      triggerRegeneration();
    }, 1500);
  }, [preferredTileIds, lastGeneratedPreferences, hasItinerary, triggerRegeneration, expandInProgress, isStreamingResponse]);

  // Flush queued regen when expandInProgress mutex releases (debounced to avoid cascade)
  useEffect(() => {
    if (!expandInProgress && !isStreamingResponse && pendingRegenRef.current) {
      pendingRegenRef.current = false;
      // Debounce: let dust settle before firing queued regen
      const timer = setTimeout(() => {
        // Dedup: skip if the expand that just finished already used current preferences
        const currentPrefs = useDocumentStore.getState().preferredTileIds;
        const lastGenerated = useDocumentStore.getState().lastGeneratedPreferences;
        if (!setsEqual(currentPrefs, lastGenerated)) {
          triggerRegeneration();
        }
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [expandInProgress, isStreamingResponse, triggerRegeneration]);

  return {
    isRegenerating,
    justHeartedId: justHeartedIdRef.current,
  };
}
