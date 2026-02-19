'use client';

/**
 * useChatSse — SSE/streaming connection manager for ChatPanel.
 *
 * Owns the `streamGraphPlan` call and all of its callbacks (onToken,
 * onNodeStatus, onPartial, onComplete, onError).  ChatPanel passes in
 * all required state-setters and refs; this hook returns a single
 * `executeStream` function that ChatPanel calls inside sendMessageCore.
 *
 * No JSX — pure side-effect hook.
 */

import { useCallback } from 'react';

import { isBootstrap } from '@/components/plan/planStateHelpers';
import { useActionLoader } from '@/hooks/useActionLoader';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { type SSENodeStatusEvent, type SSEPartialEvent, streamGraphPlan } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { classifyNodeAction, shouldShowLoaderForNode } from '@/lib/loaderConfig';
import { useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import type { GraphPlanResponse } from '@/types/document';
import type { TriggerContext } from '@/types/loader';

// Re-exported helpers kept colocated with their consumer
const READY_MESSAGE_ID_PREFIX = 'ready_';

function getErrorMessage(error: Error): string {
  const message = error.message?.toLowerCase() ?? '';
  if (message.includes('network') || message.includes('fetch') || message.includes('failed to fetch')) {
    return "Couldn't connect to the server. Please check your internet connection and try again.";
  }
  if (message.includes('timeout') || message.includes('timed out')) {
    return "The request took too long. Try a simpler query or check your connection.";
  }
  if (message.includes('rate limit') || message.includes('too many requests') || message.includes('429')) {
    return "You're sending requests too quickly. Please wait a moment before trying again.";
  }
  if (message.includes('unauthorized') || message.includes('401') || message.includes('authentication')) {
    return "Session expired. Please refresh the page and try again.";
  }
  if (message.includes('500') || message.includes('internal server') || message.includes('server error')) {
    return "Something went wrong on our end. Please try again in a few moments.";
  }
  if (message.includes('invalid') || message.includes('validation')) {
    return "Invalid request. Try rephrasing or adjusting trip details.";
  }
  return "An issue occurred. Try again or adjust the message.";
}

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ChatSseRefs {
  abortStreamRef: React.MutableRefObject<(() => void) | null>;
  isSendingRef: React.MutableRefObject<boolean>;
  autoExpandTimeoutRef: React.MutableRefObject<NodeJS.Timeout | null>;
  prevSpecialistTypesRef: React.MutableRefObject<Set<string>>;
  prevTileTypesRef: React.MutableRefObject<Set<string>>;
  prevTripInputsRef: React.MutableRefObject<{
    start_date: string | null;
    end_date: string | null;
    adults: number | null;
    children: number | null;
    budget: number | null;
    origin: string | null;
  } | null>;
  lastUserMsgIdRef: React.MutableRefObject<string | null>;
}

export interface ChatSseCallbacks {
  setHasReceivedFirstToken: (v: boolean) => void;
  setNodeStatus: (v: {
    active: boolean;
    node: string;
    label: string;
    iconKey: string;
    estimatedDurationMs: number;
    startTime: number;
    stage?: number;
    topic?: string;
  } | null) => void;
  setStreamingMessageId: (v: string | null) => void;
  setTriggerContext: (v: TriggerContext | null) => void;
  setSuggestedResponses: (v: string[]) => void;
  setSuggestedResponseMeta: (v: import('@/types/document').SuggestionChipMeta[]) => void;
  setSuggestionChips: (v: import('@/types/document').SuggestionChip[]) => void;
  setIsLoading: (v: boolean) => void;
  setSessionState: (v: Record<string, unknown> | null) => void;
  appendToMessage: (id: string, token: string) => void;
  updateMessage: (id: string, updates: Partial<import('@/types/chat').ChatMessage>) => void;
  updateMessageId: (oldId: string, newId: string) => void;
  filterMessages: (predicate: (msg: import('@/types/chat').ChatMessage) => boolean) => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: import('@/types/document').DocumentBranch[];
    tiles: Record<string, import('@/types/tile').Tile>;
    primaryBranchId: string | null;
    tripInputs?: import('@/types/document').DocumentTripInputs | null;
    readyToGenerate?: boolean;
    response?: GraphPlanResponse;
  }) => void;
  onAutoExpandItinerary?: (options?: { forceFullRebuild?: boolean }) => void;
}

export interface ExecuteStreamParams {
  body: Parameters<typeof streamGraphPlan>[0];
  streamingMsgId: string;
  isSilentPlanGeneration: boolean;
  selectedBranchId: string | null;
  triggerContext: TriggerContext | null;
  delayedLoader: ReturnType<typeof useDelayedLoader>;
  actionLoader: ReturnType<typeof useActionLoader>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useChatSse(refs: ChatSseRefs, callbacks: ChatSseCallbacks) {
  const {
    abortStreamRef,
    isSendingRef,
    autoExpandTimeoutRef,
    prevSpecialistTypesRef,
    prevTileTypesRef,
    prevTripInputsRef,
    lastUserMsgIdRef,
  } = refs;

  const {
    setHasReceivedFirstToken,
    setNodeStatus,
    setStreamingMessageId,
    setTriggerContext,
    setSuggestedResponses,
    setSuggestedResponseMeta,
    setSuggestionChips,
    setIsLoading,
    setSessionState,
    appendToMessage,
    updateMessage,
    updateMessageId,
    filterMessages,
    onPlanResult,
    onAutoExpandItinerary,
  } = callbacks;

  const executeStream = useCallback(
    (params: ExecuteStreamParams): Promise<void> => {
      const {
        body,
        streamingMsgId,
        isSilentPlanGeneration,
        selectedBranchId,
        triggerContext,
        delayedLoader,
        actionLoader,
      } = params;

      return new Promise<void>((resolve) => {
        abortStreamRef.current = streamGraphPlan(body, {
          onToken: (token: string) => {
            setHasReceivedFirstToken(true);
            delayedLoader.onTangibleOutput();
            actionLoader.onTangibleOutput();
            if (!isSilentPlanGeneration) {
              appendToMessage(streamingMsgId, token);
            }
          },

          onNodeStatus: (status: SSENodeStatusEvent['data']) => {
            if (status.status === 'started') {
              const classification = classifyNodeAction(status.node, triggerContext ?? undefined);

              if (classification) {
                const tiles = useDocumentStore.getState().document?.tiles;
                const hasTiles = tiles && Object.keys(tiles).length > 0;

                actionLoader.startLoading(
                  classification.actionType,
                  status.estimated_duration_ms,
                  {
                    verticalType: classification.verticalType,
                    hasTiles,
                  }
                );
              }

              const shouldShow = shouldShowLoaderForNode(
                status.node,
                status.estimated_duration_ms
              );
              if (shouldShow) {
                delayedLoader.startLoading(status.estimated_duration_ms);
              }

              setNodeStatus({
                active: true,
                node: status.node,
                label: status.label,
                iconKey: status.icon_key,
                estimatedDurationMs: status.estimated_duration_ms,
                startTime: Date.now(),
                stage: status.stage,
                topic: status.topic,
              });
            } else if (status.status === 'completed') {
              setNodeStatus(null);
              delayedLoader.reset();
              actionLoader.reset();
            }
          },

          onPartial: (data: SSEPartialEvent['data']) => {
            try {
              const store = useDocumentStore.getState();
              // Payload shape is validated on the complete event; partial is best-effort
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const p = data.payload as any;
              if (data.kind === 'strategy_sections') {
                store.mergeEnvelope({ strategy_sections: p });
              } else if (data.kind === 'tiles') {
                store.mergeEnvelope({ tiles: p });
              } else if (data.kind === 'trip_inputs') {
                store.mergeEnvelope({ trip_inputs: p });
              }
            } catch (partialError) {
              debugLog('[SSE] Partial merge failed (will reconcile on complete):', partialError);
            }
          },

          onComplete: (response) => {
            setStreamingMessageId(null);
            setNodeStatus(null);
            abortStreamRef.current = null;
            delayedLoader.reset();
            actionLoader.reset();
            setTriggerContext(null);

            if (!isSilentPlanGeneration) {
              const msgs = useChatStore.getState().messages;
              const streamedMsg = msgs.find((m) => m.id === streamingMsgId);
              if (
                streamedMsg?.content?.startsWith('"') &&
                streamedMsg.content.endsWith('"') &&
                streamedMsg.content.length > 2
              ) {
                updateMessage(streamingMsgId, { content: streamedMsg.content.slice(1, -1) });
              }
            }

            const data = response as unknown as GraphPlanResponse;

            setSessionState(data.session_state ?? null);

            const doc = data.document;

            const prevSpecialistTypes = prevSpecialistTypesRef.current;
            const prevTileTypes = prevTileTypesRef.current;

            const primaryBranch =
              doc.branches?.find((b) => b.is_primary) ?? doc.branches?.[0];
            onPlanResult({
              tripContextId: doc.trip_context_id ?? null,
              branches: doc.branches ?? [],
              tiles: doc.tiles ?? {},
              primaryBranchId: primaryBranch?.id ?? selectedBranchId ?? null,
              tripInputs: doc.trip_inputs ?? null,
              readyToGenerate: doc.ready_to_generate ?? false,
              response: data,
            });

            const hasTiles = doc.tiles && Object.keys(doc.tiles).length > 0;

            debugLog('[ChatPanel] Response received:', {
              hasTiles,
              tileCount: doc.tiles ? Object.keys(doc.tiles).length : 0,
              tileIds: doc.tiles ? Object.keys(doc.tiles).slice(0, 5) : [],
              plan_view_state: doc.plan_view_state,
              hasDestination: Boolean(doc.trip_inputs?.destination),
              destination: doc.trip_inputs?.destination,
              strategy_sections_count: doc.strategy_sections?.length ?? 0,
              strategy_sections: doc.strategy_sections,
              executed_strategy_topics: doc.executed_strategy_topics,
              pending_strategy_topics: doc.pending_strategy_topics,
            });

            if (hasTiles) {
              const rightPanel = document.getElementById('plan-panel');
              if (rightPanel && window.innerWidth < 768) {
                rightPanel.scrollIntoView({ behavior: 'smooth' });
              }
            }

            const isReadyToGenerate = doc.ready_to_generate === true;

            debugLog(
              `[ChatPanel] 🏷️ SSE complete:`,
              `suggestions=${JSON.stringify(doc.suggested_responses?.slice(0, 3))}`,
              `meta=${JSON.stringify(doc.suggested_response_meta?.slice(0, 2))}`,
              `viewState=${doc.plan_view_state}`,
              `dayCards=${doc.day_cards?.length ?? 'null'}`
            );
            setSuggestedResponses(doc.suggested_responses || []);
            setSuggestedResponseMeta(doc.suggested_response_meta || []);
            setSuggestionChips(doc.suggestion_chips || []);

            if (doc.origin_just_set && doc.trip_inputs?.origin) {
              debugLog('[ChatPanel] Origin set via chat:', doc.trip_inputs.origin, '- flights fetched by backend');
            }

            const freshState = useDocumentStore.getState();
            const hasItinerary = (freshState.document?.day_cards?.length ?? 0) > 0;

            const graphBuiltItinerary = (doc.day_cards?.length ?? 0) > 0;
            if (graphBuiltItinerary) {
              debugLog(`[EXPAND] SKIPPED — graph response included ${doc.day_cards!.length} day_cards`);
            }

            const freshInputs = freshState.document?.trip_inputs;
            const freshHasDates =
              (Boolean(freshInputs?.start_date) && Boolean(freshInputs?.end_date)) ||
              (freshInputs?.date_flex === true && freshInputs?.trip_duration != null);

            const newSpecialistTypes =
              (doc.strategy_sections?.map((s) => s.specialist_type).filter((t): t is string => !!t)) ?? [];
            const getTileCategory = (t: { type: string; meta?: Record<string, unknown> }) =>
              t.type === 'activity' && t.meta?.category ? String(t.meta.category) : t.type;
            const newTileCategories = new Set(Object.values(doc.tiles ?? {}).map(getTileCategory));

            const hasNewSpecialist = newSpecialistTypes.some((t) => !prevSpecialistTypes.has(t));
            const hasNewTileType = [...newTileCategories].some((t) => !prevTileTypes.has(t));
            const hasStructuralNewTileType = [...newTileCategories].some(
              (t) => t !== 'flight' && !prevTileTypes.has(t)
            );

            prevSpecialistTypesRef.current = new Set(newSpecialistTypes);
            prevTileTypesRef.current = newTileCategories;

            const tileCount = Object.keys(doc.tiles ?? {}).length;
            const viewState = doc.plan_view_state ?? 'unknown';
            const shouldExpandStructural =
              (hasItinerary || freshHasDates) &&
              (hasNewSpecialist || hasStructuralNewTileType) &&
              !isSilentPlanGeneration;
            const _prevInputs = prevTripInputsRef.current;
            const _newInputs = freshState.document?.trip_inputs;
            const _datesChanged =
              _prevInputs &&
              (_prevInputs.start_date !== _newInputs?.start_date ||
                _prevInputs.end_date !== _newInputs?.end_date);
            const _hasStrategy = (doc.strategy_sections?.length ?? 0) > 0;
            const shouldExpandDates = _datesChanged && _hasStrategy && !isSilentPlanGeneration;
            const shouldExpandCatchAll =
              _hasStrategy && !hasItinerary && freshHasDates && !isSilentPlanGeneration;
            const expandPath = graphBuiltItinerary
              ? 'GRAPH_BUILT'
              : shouldExpandStructural
                ? 'STRUCTURAL'
                : shouldExpandDates
                  ? 'DATE_CHANGE'
                  : shouldExpandCatchAll
                    ? 'CATCH_ALL'
                    : 'SKIP';
            debugLog(
              `[EXPAND] gate check: strategy=${newSpecialistTypes.length} tiles=${tileCount} ` +
              `viewState=${viewState} hasItinerary=${hasItinerary} freshHasDates=${freshHasDates} silent=${isSilentPlanGeneration} graphBuilt=${graphBuiltItinerary} ` +
              `newSpecialist=${hasNewSpecialist} newTileType=${hasNewTileType} structuralTileType=${hasStructuralNewTileType} datesChanged=${!!_datesChanged} ` +
              `prevCategories=[${[...prevTileTypes]}] newCategories=[${[...newTileCategories]}] → ${expandPath}`
            );

            const blockingViolations =
              freshState.document?.constraint_violations?.filter(
                (v) => v.severity === 'blocking'
              ) ?? [];
            if (blockingViolations.length > 0) {
              debugLog(
                '[EXPAND] BLOCKED — blocking constraint violations exist:',
                blockingViolations.map((v) => v.code)
              );
            }

            let structuralRebuildTriggered = blockingViolations.length > 0 || graphBuiltItinerary;
            if (shouldExpandStructural && !graphBuiltItinerary) {
              debugLog('[ChatPanel] Structural change detected - auto-expanding...', {
                hasNewSpecialist,
                hasNewTileType,
                prevSpecialists: [...prevSpecialistTypes],
                newSpecialists: newSpecialistTypes,
              });
              structuralRebuildTriggered = true;
              if (autoExpandTimeoutRef.current) clearTimeout(autoExpandTimeoutRef.current);
              autoExpandTimeoutRef.current = setTimeout(() => {
                if (useDocumentStore.getState().expandInProgress) {
                  debugLog('[ChatPanel] ⏭️ STRUCTURAL skipped - expand already in progress');
                  return;
                }
                onAutoExpandItinerary?.({ forceFullRebuild: true });
              }, 100);
            } else if (hasItinerary && !hasNewSpecialist && !hasNewTileType) {
              debugLog('[ChatPanel] Additive change only, itinerary preserved');
            }

            const newTripInputs = freshState.document?.trip_inputs;
            const prevInputs = prevTripInputsRef.current;

            const datesChanged =
              prevInputs &&
              (prevInputs.start_date !== newTripInputs?.start_date ||
                prevInputs.end_date !== newTripInputs?.end_date);
            const hasStrategyContent = (doc.strategy_sections?.length ?? 0) > 0;

            if (
              datesChanged &&
              hasStrategyContent &&
              !isSilentPlanGeneration &&
              !structuralRebuildTriggered
            ) {
              debugLog('[ChatPanel] Dates changed - triggering itinerary rebuild...', {
                prev: `${prevInputs!.start_date} - ${prevInputs!.end_date}`,
                new: `${newTripInputs?.start_date} - ${newTripInputs?.end_date}`,
                hasItinerary,
              });
              structuralRebuildTriggered = true;
              if (autoExpandTimeoutRef.current) clearTimeout(autoExpandTimeoutRef.current);
              autoExpandTimeoutRef.current = setTimeout(() => {
                if (useDocumentStore.getState().expandInProgress) {
                  debugLog('[ChatPanel] ⏭️ DATE_CHANGE skipped - expand already in progress');
                  return;
                }
                onAutoExpandItinerary?.({ forceFullRebuild: true });
              }, 100);
            }

            if (
              hasItinerary &&
              prevInputs &&
              !isSilentPlanGeneration &&
              !structuralRebuildTriggered
            ) {
              const travelersChanged =
                prevInputs.adults !== newTripInputs?.adults ||
                prevInputs.children !== newTripInputs?.children;
              const budgetChanged = prevInputs.budget !== newTripInputs?.budget;
              const originChanged = prevInputs.origin !== newTripInputs?.origin;
              const otherInputsChanged = travelersChanged || budgetChanged || originChanged;

              if (otherInputsChanged) {
                debugLog('[ChatPanel] Trip inputs changed - auto-rebuilding itinerary...', {
                  travelersChanged,
                  budgetChanged,
                  originChanged,
                  prev: { adults: prevInputs.adults, budget: prevInputs.budget },
                  new: { adults: newTripInputs?.adults, budget: newTripInputs?.budget },
                });
                structuralRebuildTriggered = true;
                if (autoExpandTimeoutRef.current) clearTimeout(autoExpandTimeoutRef.current);
                autoExpandTimeoutRef.current = setTimeout(() => {
                  if (useDocumentStore.getState().expandInProgress) {
                    debugLog('[ChatPanel] ⏭️ TRIP_INPUTS skipped - expand already in progress');
                    return;
                  }
                  onAutoExpandItinerary?.({ forceFullRebuild: true });
                }, 100);
              }
            }

            if (
              hasStrategyContent &&
              !hasItinerary &&
              freshHasDates &&
              !isSilentPlanGeneration &&
              !structuralRebuildTriggered &&
              !isBootstrap(doc.plan_view_state)
            ) {
              debugLog('[ChatPanel] Strategy exists but no itinerary - triggering rebuild...', {
                strategyCount: doc.strategy_sections?.length,
                hasItinerary,
                viewState,
              });
              structuralRebuildTriggered = true;
              if (autoExpandTimeoutRef.current) clearTimeout(autoExpandTimeoutRef.current);
              autoExpandTimeoutRef.current = setTimeout(() => {
                const freshDayCards = useDocumentStore.getState().document?.day_cards;
                if (freshDayCards && freshDayCards.length > 0) {
                  debugLog('[ChatPanel] ⏭️ CATCH-ALL skipped - itinerary already exists');
                  return;
                }
                onAutoExpandItinerary?.({ forceFullRebuild: true });
              }, 100);
            }

            if (isSilentPlanGeneration) {
              filterMessages((msg) => msg.id !== streamingMsgId);
            } else {
              if (isReadyToGenerate) {
                updateMessageId(streamingMsgId, `${READY_MESSAGE_ID_PREFIX}${streamingMsgId}`);
              }

              if (lastUserMsgIdRef.current && doc.ack_updates && doc.ack_updates.length > 0) {
                const userMsgId = lastUserMsgIdRef.current;
                updateMessage(userMsgId, {
                  ackStatus: doc.ack_status || 'applied',
                  ackUpdates: doc.ack_updates,
                });
              } else if (lastUserMsgIdRef.current) {
                updateMessage(lastUserMsgIdRef.current, {
                  ackStatus: 'no_change',
                });
              }
            }

            setIsLoading(false);
            isSendingRef.current = false;
            resolve();
          },

          onError: (error: Error) => {
            setStreamingMessageId(null);
            setNodeStatus(null);
            abortStreamRef.current = null;
            delayedLoader.reset();
            actionLoader.reset();
            setTriggerContext(null);
            console.error('Failed to plan trip', error);

            if (!isSilentPlanGeneration) {
              const errorMessage = getErrorMessage(error);
              const errorMsgId = `a_err_${Date.now()}`;
              updateMessageId(streamingMsgId, errorMsgId);
              updateMessage(errorMsgId, { content: errorMessage });
            }

            setIsLoading(false);
            isSendingRef.current = false;
            resolve();
          },
        });
      });
    },

    [
      abortStreamRef,
      isSendingRef,
      autoExpandTimeoutRef,
      prevSpecialistTypesRef,
      prevTileTypesRef,
      prevTripInputsRef,
      lastUserMsgIdRef,
      setHasReceivedFirstToken,
      setNodeStatus,
      setStreamingMessageId,
      setTriggerContext,
      setSuggestedResponses,
      setSuggestedResponseMeta,
      setSuggestionChips,
      setIsLoading,
      setSessionState,
      appendToMessage,
      updateMessage,
      updateMessageId,
      filterMessages,
      onPlanResult,
      onAutoExpandItinerary,
    ]
  );

  return { executeStream };
}
