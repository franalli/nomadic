'use client';

/**
 * useItineraryGeneration
 *
 * Encapsulates the itinerary generation flow:
 * - proceedWithItineraryGeneration (NDJSON streaming to expand-itinerary)
 * - Auto-trigger logic for multi-specialist trips (Path A)
 * - handleExpandToItinerary (validation-gated expand)
 * - handleSelectNights (quick pick from InlineDatePrompt)
 */

import { useCallback, useEffect, useRef } from 'react';
import { useShallow } from 'zustand/react/shallow';

import type { GenerationState } from '@/components/plan/planStateHelpers';
import { isStrategyReady, shouldAutoTriggerItinerary } from '@/components/plan/planStateHelpers';
import { apiFetch } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { consumeNdjsonEnvelopeStream } from '@/lib/streamParser';
import { useDocumentStore } from '@/state/documentStore';
import type { PlanDocumentData } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { DayCard, PlanViewState } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const STREAM_TIMEOUT_MS = 30000;
const EXPAND_REQUEST_DEDUPE_WINDOW_MS = 1200;

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface UseItineraryGenerationParams {
  uiGeneration: GenerationState | null;
  setUiGeneration: (gen: GenerationState | null) => void;
  addToast: (message: string, type?: ToastType) => void;
  planViewState: PlanViewState | null | undefined;
  docExecutedTopics: string[] | undefined;
  hasDates: boolean;
  docDayCards: DayCard[] | undefined;
  isRegenerating: boolean;
  tripInputsStartDate: string | null | undefined;
}

export interface UseItineraryGenerationResult {
  proceedWithItineraryGeneration: (options?: { forceFullRebuild?: boolean }) => Promise<void>;
  requestAutoExpandItinerary: (options?: { forceFullRebuild?: boolean }) => void;
  handleExpandToItinerary: () => Promise<void>;
  handleSelectNights: (nights: number) => Promise<void>;
  hasItineraryContent: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useItineraryGeneration({
  uiGeneration,
  setUiGeneration,
  addToast,
  planViewState,
  docExecutedTopics,
  hasDates,
  docDayCards,
  isRegenerating,
  tripInputsStartDate,
}: UseItineraryGenerationParams): UseItineraryGenerationResult {
  // Store actions (stable references via getState() pattern in callbacks)
  const {
    storeStartGeneration,
    storeIsCurrentRun,
    storeMergeEnvelope,
    storeMarkPreferencesAsApplied,
    storeCompleteGeneration,
    storeCommitTripInputs,
  } = useDocumentStore(useShallow((s) => ({
    storeStartGeneration: s.startGeneration,
    storeIsCurrentRun: s.isCurrentRun,
    storeMergeEnvelope: s.mergeEnvelope,
    storeMarkPreferencesAsApplied: s.markPreferencesAsApplied,
    storeCompleteGeneration: s.completeGeneration,
    storeCommitTripInputs: s.commitTripInputs,
  })));

  // Timezone-safe date addition utility
  const addDaysUTC = useCallback((isoDate: string, days: number): string => {
    const [y, m, d] = isoDate.split('-').map(Number);
    const dateUTC = new Date(Date.UTC(y, m - 1, d));
    dateUTC.setUTCDate(dateUTC.getUTCDate() + days);
    return dateUTC.toISOString().slice(0, 10);
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Core generation callback
  // ─────────────────────────────────────────────────────────────────────────

  const proceedWithItineraryGeneration = useCallback(
    async (options?: { forceFullRebuild?: boolean }) => {
      // RACE GUARD: Check if generation is already in progress via store
      const existingRunId = useDocumentStore.getState().currentRunId;
      if (existingRunId) {
        debugLog(
          '[proceedWithItineraryGeneration] Skipped - generation already registered:',
          existingRunId
        );
        return;
      }

      // RACE GUARD: Check if expand is already in progress
      if (useDocumentStore.getState().expandInProgress) {
        debugLog(
          '[proceedWithItineraryGeneration] Skipped - expandInProgress flag set'
        );
        return;
      }

      // Generate runId for this generation (also serves as idempotency key)
      const runId = crypto.randomUUID();

      // Start generation in documentStore - gets AbortController and registers runId
      // ATOMIC: startGeneration returns null if another generation is already running
      const abortController = storeStartGeneration(runId);

      if (!abortController) {
        debugLog(
          '[proceedWithItineraryGeneration] Skipped - startGeneration returned null'
        );
        return;
      }

      // Set expand-in-progress flag to prevent cascade with preference auto-regen
      useDocumentStore.getState().setExpandInProgress(true);

      // Set local UI generation state immediately
      setUiGeneration({ active: true, stage: 'itinerary' });

      // Timeout handling
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      const resetTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          if (storeIsCurrentRun(runId)) {
            setUiGeneration({
              active: true,
              stage: 'itinerary',
              message: 'Still working...',
            });
          }
        }, STREAM_TIMEOUT_MS);
      };

      resetTimeout();

      try {
        // FIX: Read LIVE state from store to avoid stale closure
        const freshState = useDocumentStore.getState();
        const currentDoc = freshState.document;
        const preferredTileIds = freshState.preferredTileIds;

        // Build preferences from heart state
        const tiles = currentDoc?.tiles ?? {};
        const preferredHotelIds: string[] = [];
        const preferredActivityIds: string[] = [];

        // Categorize preferred tiles by type (handle various type variants)
        for (const tileId of preferredTileIds) {
          const tile = tiles[tileId];
          const tileType = (tile?.type || '').toLowerCase();
          if (tile) {
            if (
              tileType === 'hotel' ||
              tileType === 'stay' ||
              tileType === 'accommodation'
            ) {
              preferredHotelIds.push(tileId);
            } else if (
              tileType === 'activity' ||
              tileType === 'experience' ||
              tileType === 'tour' ||
              tileType === 'attraction' ||
              tileType === 'excursion' ||
              tileType === 'ticket' ||
              tileType === 'event'
            ) {
              preferredActivityIds.push(tileId);
            }
          }
        }

        // SAFETY: Check if signal was aborted before making the fetch
        if (abortController.signal.aborted) return;

        // SAFETY: Verify we're still the current run right before fetch
        if (!storeIsCurrentRun(runId)) return;

        // Debug: Log what we're sending (using fresh state)
        debugLog('[proceedWithItineraryGeneration] Sending (fresh state):', {
          strategy_sections: currentDoc?.strategy_sections?.map((s) => ({
            type: s.specialist_type,
            content_added_count: s.content_added?.length ?? 0,
          })),
          force_full_rebuild: options?.forceFullRebuild ?? false,
        });

        // Normalize trip_inputs: when categories is empty, ensure activities='off'
        // so the builder skips all tile placement (mirrors useChatSend normalization).
        const rawTripInputs = currentDoc?.trip_inputs;
        const normalizedTripInputs = (() => {
          if (!rawTripInputs) return rawTripInputs;
          const categories = rawTripInputs.activity_settings?.categories ?? [];
          if (categories.length > 0) return rawTripInputs;
          return {
            ...rawTripInputs,
            activity_settings: {
              ...(rawTripInputs.activity_settings ?? {}),
              categories: [] as string[],
              day_preferences: {},
            },
            booking_types: {
              ...(rawTripInputs.booking_types ?? {}),
              activities: 'off' as const,
            },
          };
        })();

        const response = await apiFetch('/api/expand-itinerary', {
          method: 'POST',
          body: JSON.stringify({
            idempotency_key: runId,
            trip_inputs: normalizedTripInputs,
            strategy_sections: currentDoc?.strategy_sections,
            tiles: currentDoc?.tiles,
            preferences:
              preferredHotelIds.length > 0 || preferredActivityIds.length > 0
                ? {
                    preferred_hotel_ids: preferredHotelIds,
                    preferred_activity_ids: preferredActivityIds,
                  }
                : null,
            force_full_rebuild: options?.forceFullRebuild ?? false,
          }),
          signal: abortController.signal,
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        if (!response.body) {
          setUiGeneration(null);
          if (timeoutId) clearTimeout(timeoutId);
          return;
        }

        await consumeNdjsonEnvelopeStream(response.body, {
          onEnvelope: (planEnvelope) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', 'envelope', { type: 'envelope', plan_envelope: planEnvelope });
            debugLog('[expand-itinerary] Merging envelope:', {
              day_cards: planEnvelope?.day_cards?.length ?? 0,
              plan_view_state: planEnvelope?.plan_view_state,
            });
            storeMergeEnvelope(planEnvelope);
          },
          onProgress: (event) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', event.type, event);
            setUiGeneration({
              active: true,
              stage: event.stage,
              message: event.message,
              pct: event.pct,
            });
          },
          onDone: (event) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', event.type, event);
            const isDuplicateNoop = event.message === 'duplicate_noop';
            debugLog(
              isDuplicateNoop
                ? '[expand-itinerary] Duplicate no-op acknowledged'
                : '[expand-itinerary] Generation complete'
            );
            setUiGeneration(null);
            // Sync version from backend to prevent 409 on next PATCH
            if (typeof event.version === 'number') {
              useDocumentStore.setState({ version: event.version });
            }
            // Sync preferences to track which were used in this generation
            if (!isDuplicateNoop) {
              storeMarkPreferencesAsApplied();
            }
            // Log warning if some preferred activities couldn't fit
            if (event.dropped_preferred_count && event.dropped_preferred_count > 0) {
              debugLog(
                `[itinerary] ${event.dropped_preferred_count} preferred activities couldn't fit — not enough free days`
              );
            }
            // Show toast for activity reductions
            if (event.warnings && event.warnings.length > 0) {
              event.warnings.forEach((warning: string) => {
                addToast(warning, 'info');
              });
            }
          },
          onError: (event) => {
            if (!storeIsCurrentRun(runId)) {
              debugLog('Ignoring late event from stale run');
              return;
            }

            resetTimeout();
            debugLog('[expand-itinerary] Received event:', event.type, event);
            // CONSTRAINT_CONFLICT is a business-logic response, not an actual error.
            let parsed: Record<string, unknown> | null = null;
            try {
              parsed =
                typeof event.message === 'string'
                  ? JSON.parse(event.message)
                  : event.message;
            } catch {
              /* not JSON — treat as generic error */
            }

            if (parsed && parsed.error === 'CONSTRAINT_CONFLICT') {
              debugLog('[expand-itinerary] Constraint conflict:', parsed);
              const dayCards = parsed.day_cards as
                | Array<Record<string, unknown>>
                | undefined;
              if (dayCards && dayCards.length > 0) {
                debugLog(
                  `[expand-itinerary] Storing ${dayCards.length} partial day cards from conflict`
                );
                storeMergeEnvelope({
                  day_cards: dayCards as unknown as PlanDocumentData['day_cards'],
                  // Backend CONSTRAINT_CONFLICT sets this state intentionally; mergeEnvelope guards downgrade
                  plan_view_state:
                    'S3_PARTIAL_CONFLICT' as PlanDocumentData['plan_view_state'],
                });
              }
            } else {
              console.error('[expand-itinerary] Error received:', event.message);
            }
          },
        });
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          debugLog('Itinerary generation aborted');
          return;
        }
        console.error('Failed to expand to itinerary:', error);
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
        // Clear expand-in-progress flag
        useDocumentStore.getState().setExpandInProgress(false);
        if (storeIsCurrentRun(runId)) {
          storeCompleteGeneration();
          setUiGeneration(null);
        }
      }
      // PERF: No storeDocument in deps - function uses getState() for live reads
    },
    [storeStartGeneration, storeIsCurrentRun, storeMergeEnvelope, storeMarkPreferencesAsApplied, storeCompleteGeneration, addToast, setUiGeneration]
  );

  const queuedExpandTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastExpandRequestRef = useRef<{ key: string; ts: number } | null>(null);

  useEffect(() => {
    return () => {
      if (queuedExpandTimerRef.current) {
        clearTimeout(queuedExpandTimerRef.current);
      }
    };
  }, []);

  const scheduleItineraryGeneration = useCallback(
    (
      reason: 'sse_auto_expand' | 'path_a_auto_trigger',
      options?: { forceFullRebuild?: boolean; delayMs?: number }
    ) => {
      const forceFullRebuild = options?.forceFullRebuild ?? true;
      const dedupeKey = `${reason}|force=${forceFullRebuild ? 1 : 0}`;
      const now = Date.now();
      const last = lastExpandRequestRef.current;
      if (
        last &&
        last.key === dedupeKey &&
        now - last.ts < EXPAND_REQUEST_DEDUPE_WINDOW_MS
      ) {
        debugLog(`[itinerary scheduler] deduped duplicate request (${dedupeKey})`);
        return;
      }
      lastExpandRequestRef.current = { key: dedupeKey, ts: now };

      if (queuedExpandTimerRef.current) {
        clearTimeout(queuedExpandTimerRef.current);
      }

      const delayMs = options?.delayMs ?? (reason === 'path_a_auto_trigger' ? 500 : 120);
      queuedExpandTimerRef.current = setTimeout(() => {
        queuedExpandTimerRef.current = null;
        const state = useDocumentStore.getState();
        if (state.currentRunId || state.expandInProgress) {
          debugLog('[itinerary scheduler] skipped - generation already running');
          return;
        }
        if (
          reason === 'path_a_auto_trigger' &&
          (state.document?.day_cards?.length ?? 0) > 0
        ) {
          debugLog('[itinerary scheduler] skipped path_a - itinerary already exists');
          return;
        }
        void proceedWithItineraryGeneration({ forceFullRebuild });
      }, delayMs);
    },
    [proceedWithItineraryGeneration]
  );

  // ─────────────────────────────────────────────────────────────────────────
  // PATH A: Auto-Trigger Itinerary for Multi-Specialist Trips
  // ─────────────────────────────────────────────────────────────────────────

  // Track if we've already auto-triggered to prevent infinite loops
  const hasAutoTriggeredRef = useRef(false);

  // Check if itinerary content exists
  const hasItineraryContent = (docDayCards?.length ?? 0) > 0;

  // Reset auto-trigger flag when itinerary is cleared and we're back at S2
  useEffect(() => {
    if (!hasItineraryContent && isStrategyReady(planViewState)) {
      hasAutoTriggeredRef.current = false;
    }
  }, [hasItineraryContent, planViewState]);

  // Auto-trigger effect
  useEffect(() => {
    // Skip if already triggered
    if (hasAutoTriggeredRef.current) return;

    // RACE GUARD: Skip if itinerary generation is already active
    if (uiGeneration?.active) return;

    // Check auto-trigger conditions (skip when backend state not yet received)
    const shouldAutoTrigger = planViewState
      ? shouldAutoTriggerItinerary(
          planViewState,
          docExecutedTopics,
          hasDates,
          uiGeneration,
          hasItineraryContent
        )
      : false;

    if (shouldAutoTrigger) {
      hasAutoTriggeredRef.current = true;
      scheduleItineraryGeneration('path_a_auto_trigger', {
        forceFullRebuild: true,
        delayMs: 500,
      });
    }
  }, [
    planViewState,
    docExecutedTopics,
    hasDates,
    uiGeneration,
    hasItineraryContent,
    scheduleItineraryGeneration,
  ]);

  const requestAutoExpandItinerary = useCallback(
    (options?: { forceFullRebuild?: boolean }) => {
      scheduleItineraryGeneration('sse_auto_expand', {
        forceFullRebuild: options?.forceFullRebuild ?? true,
        delayMs: 120,
      });
    },
    [scheduleItineraryGeneration]
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Validation-gated expand handler
  // ─────────────────────────────────────────────────────────────────────────

  const handleExpandToItinerary = useCallback(async () => {
    // UI-only gate: show toast when user clicks expand during regen (not a mutex)
    if (isRegenerating) {
      addToast('Plan is updating, please wait...', 'info');
      return;
    }

    // FIX: Read DIRECTLY from store to avoid stale closure
    const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;

    // GATE 1: Require start_date
    if (!currentTripInputs?.start_date) {
      addToast('Set a start date first', 'info');
      return;
    }

    // GATE 2: Require end_date
    if (!currentTripInputs?.end_date) {
      addToast('Add return date to see itinerary', 'info');
      return;
    }

    // All gates passed - proceed with itinerary generation
    await proceedWithItineraryGeneration();
  }, [isRegenerating, addToast, proceedWithItineraryGeneration]);

  // ─────────────────────────────────────────────────────────────────────────
  // Quick pick handler (InlineDatePrompt)
  // ─────────────────────────────────────────────────────────────────────────

  const handleSelectNights = useCallback(
    async (nights: number) => {
      if (!tripInputsStartDate) return;

      // Calculate end date (timezone-safe)
      const endDateStr = addDaysUTC(tripInputsStartDate, nights);

      // Update trip inputs and await confirmation
      const success = await storeCommitTripInputs({ end_date: endDateStr });

      // Just confirm the date was set - DON'T auto-trigger expand-itinerary
      if (success) {
        addToast('Trip length set', 'confirmation');
      }
    },
    [tripInputsStartDate, addDaysUTC, storeCommitTripInputs, addToast]
  );

  return {
    proceedWithItineraryGeneration,
    requestAutoExpandItinerary,
    handleExpandToItinerary,
    handleSelectNights,
    hasItineraryContent,
  };
}
