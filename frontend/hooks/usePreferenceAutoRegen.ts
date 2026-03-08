/**
 * startPreferenceAutoRegen
 *
 * Automatically regenerates itinerary when user preferences (hearts) change.
 * Debounced (1.5s) to batch rapid heart toggles into a single expand call.
 *
 * Module-level subscription (not a React hook) — avoids root re-renders from
 * the 9 separate useDocumentStore() calls the previous hook version had.
 *
 * @see docs/ux_unified_architecture.md - Heart Preference System
 */

import { apiFetch } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { consumeNdjsonEnvelopeStream } from '@/lib/streamParser';
import { useDocumentStore } from '@/state/documentStore';

/**
 * Compare two sets for equality.
 */
export function setsEqual(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) {
    if (!b.has(id)) return false;
  }
  return true;
}

// ─── Module-level refs (stable across React renders) ─────────────────────────

let abortRef: AbortController | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let lastPrefsRef: Set<string> = new Set();
let pendingRegen = false;
let trailingRegenTimer: ReturnType<typeof setTimeout> | null = null;

// Track whether startPreferenceAutoRegen is already running
let cleanupFn: (() => void) | null = null;

// ─── Core regeneration logic ─────────────────────────────────────────────────

export async function triggerRegeneration(
  forceFullRebuild = false,
  refreshActivityCategories?: string[],
): Promise<void> {
  // === FULL DIAGNOSTIC — LAYER 10: REGEN ENTRY ===
  debugLog(
    '[DIAG:REGEN_ENTRY]',
    `forceFullRebuild: ${forceFullRebuild}`,
    `refreshActivityCategories: ${JSON.stringify(refreshActivityCategories)}`,
    `isRegenerating: ${useDocumentStore.getState().isRegenerating}`,
    `expandInProgress: ${useDocumentStore.getState().expandInProgress}`,
  );
  // === END DIAGNOSTIC ===

  // Race condition guard — expandInProgress is the sole mutex.
  // isRegenerating may already be true as early visual feedback (e.g. activity
  // sheet save sets it before the PATCH completes) — that's intentional.
  const { expandInProgress: alreadyExpanding } =
    useDocumentStore.getState();
  if (alreadyExpanding) {
    // === DIAGNOSTIC ===
    debugLog('[DIAG:REGEN_BLOCKED] expand already in progress — skipping');
    // === END DIAGNOSTIC ===
    return;
  }

  // Abort any in-flight regen before starting a new one
  abortRef?.abort();
  abortRef = new AbortController();
  const signal = abortRef.signal;

  const { setExpandInProgress, setRegenerationState, awaitPreferencePatch, markPreferencesAsApplied } =
    useDocumentStore.getState();

  // Set expand-in-progress flag to prevent cascade
  setExpandInProgress(true);
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

    // === FULL DIAGNOSTIC — LAYER 11: EXPAND REQUEST ===
    debugLog('[DIAG:EXPAND_REQ]', `body=${JSON.stringify({
      force_full_rebuild: forceFullRebuild,
      refresh_activity_categories: refreshActivityCategories,
      tiles_count: Object.keys(document?.tiles ?? {}).length,
      strategy_sections_count: document?.strategy_sections?.length,
    })}`);
    // === END DIAGNOSTIC ===

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
        ...(forceFullRebuild ? { force_full_rebuild: true } : {}),
        ...(refreshActivityCategories ? { refresh_activity_categories: refreshActivityCategories } : {}),
      }),
    });

    // === DIAGNOSTIC ===
    debugLog('[DIAG:EXPAND_RES]', `status=${response.status}`, `ok=${response.ok}`);
    // === END DIAGNOSTIC ===

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    if (response.body) {
      await consumeNdjsonEnvelopeStream(response.body, {
        onEnvelope: (planEnvelope) => {
          useDocumentStore.getState().mergeEnvelope(planEnvelope);
        },
        onDone: (event) => {
          // CRITICAL: Sync version from backend to prevent 409 on next PATCH
          // expand-itinerary persists changes which increments version
          if (typeof event.version === 'number') {
            useDocumentStore.setState({ version: event.version });
          }
          // Log warning if some preferred activities couldn't fit
          if (event.dropped_preferred_count && event.dropped_preferred_count > 0) {
            debugLog(
              `[itinerary] ${event.dropped_preferred_count} preferred activities couldn't fit — not enough free days`
            );
          }
        },
        onError: (event) => {
          throw new Error(event.message || 'Regeneration failed');
        },
      });
    }

    // Success - mark preferences as applied
    markPreferencesAsApplied();
  } catch (error) {
    if (signal.aborted) return; // Superseded by a newer regen — silent exit
    console.error('[usePreferenceAutoRegen] Regeneration failed:', error);
    // No toast for preference regen - it's a background operation
  } finally {
    useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
    useDocumentStore.getState().setExpandInProgress(false);
  }
}

// ─── Module-level subscription ────────────────────────────────────────────────

/**
 * startPreferenceAutoRegen
 *
 * Sets up two zustand subscriptions that watch for preference changes and
 * trigger itinerary regeneration. Returns a cleanup function.
 *
 * Idempotent: if already running, returns the existing cleanup.
 *
 * Uses plain subscribe(listener) form compatible with vanilla create() stores.
 * Selector extraction and equality checks are done inside the listener.
 */
export function startPreferenceAutoRegen(): () => void {
  // Idempotent guard: if already running, return existing cleanup
  if (cleanupFn !== null) return cleanupFn;

  // Initialize last prefs from current store state so the first subscription
  // callback correctly detects diffs rather than treating current state as a change
  lastPrefsRef = new Set(useDocumentStore.getState().preferredTileIds);

  // ─── Subscription 1: watch preferredTileIds for changes ──────────────────
  //
  // Plain subscribe receives (newState, prevState). We extract preferredTileIds
  // and check for equality ourselves (subscribeWithSelector is not used here).
  const unsubPrefs = useDocumentStore.subscribe((state, prevState) => {
    const prefs = state.preferredTileIds;
    const prevPrefs = prevState.preferredTileIds;

    // Skip if the Set reference didn't change (fast path)
    if (prefs === prevPrefs) return;

    // Skip if Set contents are equal
    if (setsEqual(prefs, prevPrefs)) return;

    // Read all other needed state at trigger time
    const dayCards = state.document?.day_cards;
    const expandInProgress = state.expandInProgress;
    const isStreamingResponse = state.currentRunId !== null;
    const lastGeneratedPreferences = state.lastGeneratedPreferences;

    // Skip if no itinerary to regenerate
    const hasItinerary = (dayCards?.length ?? 0) > 0;
    if (!hasItinerary) {
      lastPrefsRef = new Set(prefs);
      return;
    }

    // Skip if expand-itinerary is already running (prevents cascade)
    // Queue for later instead of silently dropping
    if (expandInProgress || isStreamingResponse) {
      debugLog('[usePreferenceAutoRegen] Queuing - expand or streaming in progress');
      pendingRegen = true;
      lastPrefsRef = new Set(prefs);
      return;
    }

    // Check if preferences changed from last known
    if (setsEqual(prefs, lastPrefsRef)) {
      return; // No change
    }

    // Update last prefs before triggering regen
    lastPrefsRef = new Set(prefs);

    // Check if these preferences differ from last GENERATED preferences
    // (avoids re-triggering after regen completes and syncs)
    if (setsEqual(prefs, lastGeneratedPreferences)) {
      return;
    }

    // Debounce: batch rapid heart toggles into a single regen (1.5s window)
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      triggerRegeneration();
    }, 1500);
  });

  // ─── Subscription 2: flush queued regen on expandInProgress mutex release ─
  const unsubExpand = useDocumentStore.subscribe((state, prevState) => {
    const expandInProgress = state.expandInProgress;
    const prevExpandInProgress = prevState.expandInProgress;

    // Only act on the transition from true → false
    if (expandInProgress || !prevExpandInProgress) return;

    const isStreamingResponse = state.currentRunId !== null;
    if (!isStreamingResponse && pendingRegen) {
      pendingRegen = false;
      // Debounce: let dust settle before firing queued regen
      trailingRegenTimer = setTimeout(() => {
        // Dedup: skip if the expand that just finished already used current preferences
        const currentPrefs = useDocumentStore.getState().preferredTileIds;
        const lastGenerated = useDocumentStore.getState().lastGeneratedPreferences;
        if (!setsEqual(currentPrefs, lastGenerated)) {
          triggerRegeneration();
        }
      }, 500);
    }
  });

  cleanupFn = () => {
    unsubPrefs();
    unsubExpand();
    abortRef?.abort();
    if (debounceTimer) clearTimeout(debounceTimer);
    if (trailingRegenTimer) { clearTimeout(trailingRegenTimer); trailingRegenTimer = null; }
    cleanupFn = null;
    lastPrefsRef = new Set();
    pendingRegen = false;
  };

  return cleanupFn;
}
