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
import {
  isStrategyReady,
  shouldAutoTriggerItinerary,
} from '@/components/plan/planStateHelpers';
import { apiFetch } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { consumeNdjsonEnvelopeStream } from '@/lib/streamParser';
import { useDocumentStore } from '@/state/documentStore';
import type { PlanDocumentData } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { DayCard, PlanViewState } from '@/types/plan-envelope';

const STREAM_TIMEOUT_MS = 30000;
const EXPAND_REQUEST_DEDUPE_WINDOW_MS = 1200;

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

export function useItineraryGenerationController({
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
  const {
    storeStartGeneration,
    storeIsCurrentRun,
    storeMergeEnvelope,
    storeMarkPreferencesAsApplied,
    storeCompleteGeneration,
    storeCommitTripInputs,
  } = useDocumentStore(
    useShallow((s) => ({
      storeStartGeneration: s.startGeneration,
      storeIsCurrentRun: s.isCurrentRun,
      storeMergeEnvelope: s.mergeEnvelope,
      storeMarkPreferencesAsApplied: s.markPreferencesAsApplied,
      storeCompleteGeneration: s.completeGeneration,
      storeCommitTripInputs: s.commitTripInputs,
    }))
  );

  const addDaysUTC = useCallback((isoDate: string, days: number): string => {
    const [y, m, d] = isoDate.split('-').map(Number);
    const dateUTC = new Date(Date.UTC(y, m - 1, d));
    dateUTC.setUTCDate(dateUTC.getUTCDate() + days);
    return dateUTC.toISOString().slice(0, 10);
  }, []);

  const proceedWithItineraryGeneration = useCallback(
    async (options?: { forceFullRebuild?: boolean }) => {
      const existingRunId = useDocumentStore.getState().currentRunId;
      if (existingRunId) {
        debugLog(
          '[proceedWithItineraryGeneration] Skipped - generation already registered:',
          existingRunId
        );
        return;
      }

      if (useDocumentStore.getState().expandInProgress) {
        debugLog('[proceedWithItineraryGeneration] Skipped - expandInProgress flag set');
        return;
      }

      const runId = crypto.randomUUID();
      const abortController = storeStartGeneration(runId);

      if (!abortController) {
        debugLog('[proceedWithItineraryGeneration] Skipped - startGeneration returned null');
        return;
      }

      useDocumentStore.getState().setExpandInProgress(true);
      setUiGeneration({ active: true, stage: 'itinerary' });

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
        const freshState = useDocumentStore.getState();
        const currentDoc = freshState.document;
        const preferredTileIds = freshState.preferredTileIds;
        const tiles = currentDoc?.tiles ?? {};
        const preferredHotelIds: string[] = [];
        const preferredActivityIds: string[] = [];

        for (const tileId of preferredTileIds) {
          const tile = tiles[tileId];
          const tileType = (tile?.type || '').toLowerCase();
          if (!tile) continue;
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

        if (abortController.signal.aborted) return;
        if (!storeIsCurrentRun(runId)) return;

        debugLog('[proceedWithItineraryGeneration] Sending (fresh state):', {
          strategy_sections: currentDoc?.strategy_sections?.map((s) => ({
            type: s.specialist_type,
            content_added_count: s.content_added?.length ?? 0,
          })),
          force_full_rebuild: options?.forceFullRebuild ?? false,
        });

        const rawTripInputs = currentDoc?.trip_inputs;
        const normalizedTripInputs = (() => {
          if (!rawTripInputs) return rawTripInputs;
          const categories = rawTripInputs.activity_settings?.categories ?? [];
          if (categories.length > 0) return rawTripInputs;
          // Empty categories means "no category preference" — it does NOT imply the
          // user disabled activities. `booking_types.activities` is the authoritative
          // disable signal (set explicitly via the settings UI / activity toggle), so
          // it is passed through unchanged. Forcing it to 'off' here wrongly wiped the
          // surviving general activities when the user removed only their sole
          // specialist category (e.g. "remove diving" → categories=[] but activities
          // still 'suggested'), collapsing the plan into all-Free-Day cards. The
          // backend maps categories=[] + activities!='off' to "no filter" and places
          // the remaining activity tiles; categories=[] + activities='off' skips all.
          return {
            ...rawTripInputs,
            activity_settings: {
              ...(rawTripInputs.activity_settings ?? {}),
              categories: [] as string[],
              day_preferences: {},
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
            debugLog('[expand-itinerary] Received event:', 'envelope', {
              type: 'envelope',
              plan_envelope: planEnvelope,
            });
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
            if (typeof event.version === 'number') {
              useDocumentStore.setState({ version: event.version });
            }
            if (!isDuplicateNoop) {
              storeMarkPreferencesAsApplied();
            }
            if (event.dropped_preferred_count && event.dropped_preferred_count > 0) {
              debugLog(
                `[itinerary] ${event.dropped_preferred_count} preferred activities couldn't fit — not enough free days`
              );
            }
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
            let parsed: Record<string, unknown> | null = null;
            try {
              parsed =
                typeof event.message === 'string'
                  ? JSON.parse(event.message)
                  : event.message;
            } catch {
              // treat as generic error
            }

            if (parsed && parsed.error === 'CONSTRAINT_CONFLICT') {
              debugLog('[expand-itinerary] Constraint conflict:', parsed);
              const dayCards = parsed.day_cards as Array<Record<string, unknown>> | undefined;
              const backendPlanViewState =
                typeof parsed.plan_view_state === 'string'
                  ? (parsed.plan_view_state as PlanDocumentData['plan_view_state'])
                  : undefined;

              if (dayCards && dayCards.length > 0) {
                debugLog(
                  `[expand-itinerary] Storing ${dayCards.length} partial day cards from conflict`
                );
                storeMergeEnvelope({
                  day_cards: dayCards as unknown as PlanDocumentData['day_cards'],
                  ...(backendPlanViewState
                    ? { plan_view_state: backendPlanViewState }
                    : {}),
                });
              }

              if (!backendPlanViewState) {
                debugLog(
                  '[expand-itinerary] Conflict payload missing plan_view_state; preserving current state'
                );
              }
            } else if (parsed && parsed.error === 'TRIP_TOO_SHORT') {
              debugLog('[expand-itinerary] Trip too short:', parsed);
              addToast(
                'Trips need at least 2 days — extend your dates to generate an itinerary.',
                'info'
              );
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
        useDocumentStore.getState().setExpandInProgress(false);
        if (storeIsCurrentRun(runId)) {
          storeCompleteGeneration();
          setUiGeneration(null);
        }
      }
    },
    [
      addToast,
      setUiGeneration,
      storeCompleteGeneration,
      storeIsCurrentRun,
      storeMarkPreferencesAsApplied,
      storeMergeEnvelope,
      storeStartGeneration,
    ]
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

  const hasAutoTriggeredRef = useRef(false);
  const hasItineraryContent = (docDayCards?.length ?? 0) > 0;

  useEffect(() => {
    if (!hasItineraryContent && isStrategyReady(planViewState)) {
      hasAutoTriggeredRef.current = false;
    }
  }, [hasItineraryContent, planViewState]);

  useEffect(() => {
    if (hasAutoTriggeredRef.current || uiGeneration?.active) return;

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
    docExecutedTopics,
    hasDates,
    hasItineraryContent,
    planViewState,
    scheduleItineraryGeneration,
    uiGeneration,
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

  const handleExpandToItinerary = useCallback(async () => {
    if (isRegenerating) {
      addToast('Plan is updating, please wait...', 'info');
      return;
    }

    const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;

    if (!currentTripInputs?.start_date) {
      addToast('Set a start date first', 'info');
      return;
    }

    if (!currentTripInputs?.end_date) {
      addToast('Add return date to see itinerary', 'info');
      return;
    }

    await proceedWithItineraryGeneration();
  }, [addToast, isRegenerating, proceedWithItineraryGeneration]);

  const handleSelectNights = useCallback(
    async (nights: number) => {
      if (!tripInputsStartDate) return;

      const endDateStr = addDaysUTC(tripInputsStartDate, nights);
      const success = await storeCommitTripInputs({ end_date: endDateStr });

      if (success) {
        addToast('Trip length set', 'confirmation');
      }
    },
    [addDaysUTC, addToast, storeCommitTripInputs, tripInputsStartDate]
  );

  return {
    proceedWithItineraryGeneration,
    requestAutoExpandItinerary,
    handleExpandToItinerary,
    handleSelectNights,
    hasItineraryContent,
  };
}
