/**
 * usePreferenceAutoRegen
 *
 * Automatically regenerates itinerary when user preferences (hearts) change.
 * Triggers INSTANTLY (no debounce) for responsive UX.
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
  const setRegenerationState = useDocumentStore((s) => s.setRegenerationState);
  const awaitPreferencePatch = useDocumentStore((s) => s.awaitPreferencePatch);
  const markPreferencesAsApplied = useDocumentStore((s) => s.markPreferencesAsApplied);

  // Track the tile that was just hearted (for UI feedback)
  const justHeartedIdRef = useRef<string | null>(null);

  // Track if this is the initial mount
  const isInitialMount = useRef(true);

  // Track last known preferences to detect which tile changed
  const lastPrefsRef = useRef<Set<string>>(new Set());

  // Check if itinerary exists
  const hasItinerary = (dayCards?.length ?? 0) > 0;

  // Regeneration function
  const triggerRegeneration = useCallback(async () => {
    // Race condition guard
    if (useDocumentStore.getState().isRegenerating) {
      console.log('[usePreferenceAutoRegen] ⏭️ Skipping - already regenerating (race guard)');
      return;
    }

    console.log('[usePreferenceAutoRegen] 🔄 Instant regeneration triggered');

    setRegenerationState({ isRegenerating: true });

    try {
      // Wait for preference PATCH to complete first
      await awaitPreferencePatch();

      // Build request body
      const document = useDocumentStore.getState().document;
      const prefs = useDocumentStore.getState().preferredTileIds;

      // Separate hotel and activity preferences
      const hotelIds: string[] = [];
      const activityIds: string[] = [];

      if (document?.tiles) {
        for (const id of prefs) {
          const tile = document.tiles[id];
          if (tile) {
            if (tile.type === 'hotel') {
              hotelIds.push(id);
            } else if (tile.type === 'activity') {
              activityIds.push(id);
            }
          }
        }
      }

      const response = await apiFetch('/api/expand-itinerary', {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: crypto.randomUUID(),
          trip_inputs: document?.trip_inputs,
          strategy_sections: document?.strategy_sections,
          tiles: document?.tiles,
          preferences: {
            preferred_hotel_ids: hotelIds,
            preferred_activity_ids: activityIds,
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
      console.log('[usePreferenceAutoRegen] ✅ Regeneration complete');
    } catch (error) {
      console.error('[usePreferenceAutoRegen] ❌ Regeneration failed:', error);
      // No toast for preference regen - it's a background operation
    } finally {
      setRegenerationState({ isRegenerating: false });
      justHeartedIdRef.current = null;
    }
  }, [awaitPreferencePatch, markPreferencesAsApplied, setRegenerationState]);

  // Watch for preference changes
  useEffect(() => {
    // Skip initial mount
    if (isInitialMount.current) {
      isInitialMount.current = false;
      lastPrefsRef.current = new Set(preferredTileIds);
      console.log('[usePreferenceAutoRegen] 📸 Initial preferences captured');
      return;
    }

    // Skip if no itinerary to regenerate
    if (!hasItinerary) {
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
      console.log('[usePreferenceAutoRegen] ⏭️ Preferences match last generated, skipping');
      return;
    }

    console.log('[usePreferenceAutoRegen] 💚 Preference changed:', justHeartedIdRef.current);

    // Trigger instant regeneration (no debounce)
    triggerRegeneration();
  }, [preferredTileIds, lastGeneratedPreferences, hasItinerary, triggerRegeneration]);

  return {
    isRegenerating,
    justHeartedId: justHeartedIdRef.current,
  };
}
