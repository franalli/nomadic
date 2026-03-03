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

import { useCallback, useEffect, useRef } from 'react';

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
  activeStreamRequestIdRef: React.MutableRefObject<string | null>;
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
  scrollToBottom: (force?: boolean) => void;
  scrollPanelIntoView: () => void;
}

export interface ExecuteStreamParams {
  body: Parameters<typeof streamGraphPlan>[0];
  requestId: string;
  streamingMsgId: string;
  isSilentPlanGeneration: boolean;
  selectedBranchId: string | null;
  envelopeGeneration: number;
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
    activeStreamRequestIdRef,
    autoExpandTimeoutRef,
    prevSpecialistTypesRef,
    prevTileTypesRef,
    prevTripInputsRef,
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
    scrollToBottom,
    scrollPanelIntoView,
  } = callbacks;

  const reconcileTimerRef = useRef<NodeJS.Timeout | null>(null);
  const queueCompletionScroll = useCallback(() => {
    requestAnimationFrame(() => {
      scrollPanelIntoView();
      scrollToBottom(true);
      requestAnimationFrame(() => {
        scrollPanelIntoView();
        scrollToBottom(true);
      });
      setTimeout(() => {
        scrollPanelIntoView();
        scrollToBottom(true);
      }, 150);
    });
  }, [scrollToBottom, scrollPanelIntoView]);

  useEffect(() => {
    return () => {
      if (reconcileTimerRef.current) {
        clearTimeout(reconcileTimerRef.current);
        reconcileTimerRef.current = null;
      }
    };
  }, []);

  const executeStream = useCallback(
    (params: ExecuteStreamParams): Promise<void> => {
      const {
        body,
        requestId,
        streamingMsgId,
        isSilentPlanGeneration,
        selectedBranchId,
        envelopeGeneration,
        triggerContext,
        delayedLoader,
        actionLoader,
      } = params;

      return new Promise<void>((resolve) => {
        const isStaleRequest = () => activeStreamRequestIdRef.current !== requestId;

        if (reconcileTimerRef.current) {
          clearTimeout(reconcileTimerRef.current);
          reconcileTimerRef.current = null;
        }

        if (isStaleRequest()) {
          debugLog('[SSE] Skipping stream setup for stale request');
          resolve();
          return;
        }

        abortStreamRef.current = streamGraphPlan(body, {
          onToken: (token: string) => {
            if (isStaleRequest()) return;
            setHasReceivedFirstToken(true);
            delayedLoader.onTangibleOutput();
            actionLoader.onTangibleOutput();
            if (!isSilentPlanGeneration) {
              appendToMessage(streamingMsgId, token);
            }
          },

          onNodeStatus: (status: SSENodeStatusEvent['data']) => {
            if (isStaleRequest()) return;
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
            if (isStaleRequest()) return;
            try {
              const store = useDocumentStore.getState();
              // Payload shape is validated on the complete event; partial is best-effort
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const p = data.payload as any;
              if (data.kind === 'strategy_sections') {
                store.mergeEnvelope({ strategy_sections: p }, envelopeGeneration);
              } else if (data.kind === 'tiles') {
                store.mergeEnvelope({ tiles: p }, envelopeGeneration);
              } else if (data.kind === 'trip_inputs') {
                store.mergeEnvelope({ trip_inputs: p }, envelopeGeneration);
              }
            } catch (partialError) {
              debugLog('[SSE] Partial merge failed (will reconcile on complete):', partialError);
            }
          },

          onComplete: (response) => {
            if (isStaleRequest()) {
              debugLog('[SSE] Ignoring stale stream complete event');
              resolve();
              return;
            }

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
            let planResultApplied = true;
            try {
              onPlanResult({
                tripContextId: doc.trip_context_id ?? null,
                branches: doc.branches ?? [],
                tiles: doc.tiles ?? {},
                primaryBranchId: primaryBranch?.id ?? selectedBranchId ?? null,
                tripInputs: doc.trip_inputs ?? null,
                readyToGenerate: doc.ready_to_generate ?? false,
                response: data,
              });
            } catch (planResultError) {
              planResultApplied = false;
              console.error('[ChatPanel] Failed to apply stream result, reconciling from server:', planResultError);
            }

            const hasTiles = doc.tiles && Object.keys(doc.tiles).length > 0;

            debugLog('[ChatPanel] Response received:', {
              hasTiles,
              tileCount: doc.tiles ? Object.keys(doc.tiles).length : 0,
              tileIds: doc.tiles ? Object.keys(doc.tiles).slice(0, 5) : [],
              plan_view_state: doc.plan_view_state,
              hasDestination: Boolean(doc.trip_inputs?.destination),
              destination: doc.trip_inputs?.destination,
              strategy_sections_count: doc.strategy_sections?.length ?? 0,
              strategy_section_ids: doc.strategy_sections?.map((s: any) => s.id),
              executed_strategy_topic_count: doc.executed_strategy_topics?.length ?? 0,
              pending_strategy_topic_count: doc.pending_strategy_topics?.length ?? 0,
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
            const prevInputs = prevTripInputsRef.current;
            const newTripInputs = freshState.document?.trip_inputs;
            const hasStrategyContent = (doc.strategy_sections?.length ?? 0) > 0;

            const shouldExpandStructural =
              (hasItinerary || freshHasDates) &&
              (hasNewSpecialist || hasStructuralNewTileType) &&
              !isSilentPlanGeneration;
            const datesChanged =
              prevInputs &&
              (prevInputs.start_date !== newTripInputs?.start_date ||
                prevInputs.end_date !== newTripInputs?.end_date);
            const shouldExpandDates = datesChanged && hasStrategyContent && !isSilentPlanGeneration;
            const travelersChanged =
              prevInputs &&
              (prevInputs.adults !== newTripInputs?.adults ||
                prevInputs.children !== newTripInputs?.children);
            const budgetChanged = prevInputs && prevInputs.budget !== newTripInputs?.budget;
            const originChanged = prevInputs && prevInputs.origin !== newTripInputs?.origin;
            const otherInputsChanged = Boolean(travelersChanged || budgetChanged || originChanged);
            const shouldExpandTripInputs =
              hasItinerary &&
              Boolean(prevInputs) &&
              otherInputsChanged &&
              !isSilentPlanGeneration;
            const shouldExpandCatchAll =
              hasStrategyContent &&
              !hasItinerary &&
              freshHasDates &&
              !isSilentPlanGeneration &&
              !isBootstrap(doc.plan_view_state);

            debugLog(
              `[EXPAND] gate check: strategy=${newSpecialistTypes.length} tiles=${tileCount} ` +
              `viewState=${viewState} hasItinerary=${hasItinerary} freshHasDates=${freshHasDates} silent=${isSilentPlanGeneration} graphBuilt=${graphBuiltItinerary} ` +
              `newSpecialist=${hasNewSpecialist} newTileType=${hasNewTileType} structuralTileType=${hasStructuralNewTileType} datesChanged=${!!datesChanged} ` +
              `travelersChanged=${!!travelersChanged} budgetChanged=${!!budgetChanged} originChanged=${!!originChanged} ` +
              `prevCategories=[${[...prevTileTypes]}] newCategories=[${[...newTileCategories]}]`
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

            let expandReason: 'STRUCTURAL' | 'DATE_CHANGE' | 'TRIP_INPUTS' | 'CATCH_ALL' | null =
              null;
            if (!graphBuiltItinerary && blockingViolations.length === 0) {
              if (shouldExpandStructural) {
                expandReason = 'STRUCTURAL';
              } else if (shouldExpandDates) {
                expandReason = 'DATE_CHANGE';
              } else if (shouldExpandTripInputs) {
                expandReason = 'TRIP_INPUTS';
              } else if (shouldExpandCatchAll) {
                expandReason = 'CATCH_ALL';
              }
            }

            if (!expandReason && hasItinerary && !hasNewSpecialist && !hasNewTileType) {
              debugLog('[ChatPanel] Additive change only, itinerary preserved');
            }

            if (expandReason) {
              debugLog('[ChatPanel] Auto-expand scheduled:', {
                reason: expandReason,
                prevDates: prevInputs
                  ? `${prevInputs.start_date ?? 'null'} - ${prevInputs.end_date ?? 'null'}`
                  : null,
                newDates: `${newTripInputs?.start_date ?? 'null'} - ${newTripInputs?.end_date ?? 'null'}`,
              });

              if (autoExpandTimeoutRef.current) clearTimeout(autoExpandTimeoutRef.current);
              autoExpandTimeoutRef.current = setTimeout(() => {
                const activeRequestId = activeStreamRequestIdRef.current;
                if (activeRequestId !== null && activeRequestId !== requestId) {
                  debugLog(`[ChatPanel] ⏭️ ${expandReason} skipped - stale request`);
                  return;
                }
                const latest = useDocumentStore.getState();
                if (latest.expandInProgress) {
                  debugLog(`[ChatPanel] ⏭️ ${expandReason} skipped - expand already in progress`);
                  return;
                }
                if (
                  expandReason === 'CATCH_ALL' &&
                  (latest.document?.day_cards?.length ?? 0) > 0
                ) {
                  debugLog('[ChatPanel] ⏭️ CATCH_ALL skipped - itinerary already exists');
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
            }

            // Reconcile from persisted document when stream payload looks incomplete
            // or the in-memory apply path threw. This prevents "manual refresh required".
            const responseHasStrategy = (doc.strategy_sections?.length ?? 0) > 0;
            const responseHasDayCards = (doc.day_cards?.length ?? 0) > 0;
            const expectsDayCards = Boolean(
              (doc.trip_inputs?.start_date && doc.trip_inputs?.end_date) ||
              (doc.trip_inputs?.date_flex === true && doc.trip_inputs?.trip_duration != null)
            );
            const needsReconcile =
              !planResultApplied ||
              !responseHasStrategy ||
              (expectsDayCards && !responseHasDayCards);

            if (needsReconcile) {
              const reconcileTimer = setTimeout(async () => {
                if (isSendingRef.current) return;
                try {
                  await useDocumentStore.getState().fetchDocument();
                } catch {
                  debugLog('[ChatPanel] Reconcile fetch failed');
                }
                if (reconcileTimerRef.current === reconcileTimer) {
                  reconcileTimerRef.current = null;
                }
              }, 1500);
              reconcileTimerRef.current = reconcileTimer;
            }

            setIsLoading(false);
            isSendingRef.current = false;
            activeStreamRequestIdRef.current = null;
            queueCompletionScroll();
            resolve();
          },

          onError: (error: Error) => {
            if (isStaleRequest()) {
              debugLog('[SSE] Ignoring stale stream error event');
              resolve();
              return;
            }

            setStreamingMessageId(null);
            setNodeStatus(null);
            abortStreamRef.current = null;
            delayedLoader.reset();
            actionLoader.reset();
            setTriggerContext(null);
            if (reconcileTimerRef.current) {
              clearTimeout(reconcileTimerRef.current);
              reconcileTimerRef.current = null;
            }
            console.error('Failed to plan trip', error);

            if (!isSilentPlanGeneration) {
              const errorMessage = getErrorMessage(error);
              const errorMsgId = `a_err_${Date.now()}`;
              updateMessageId(streamingMsgId, errorMsgId);
              updateMessage(errorMsgId, { content: errorMessage });
            } else {
              useChatStore.getState().addMessage({
                id: `a_err_${Date.now()}`,
                role: 'assistant',
                content: getErrorMessage(error),
              });
            }

            setIsLoading(false);
            isSendingRef.current = false;
            activeStreamRequestIdRef.current = null;
            queueCompletionScroll();
            resolve();
          },
        });
      });
    },

    [
      abortStreamRef,
      isSendingRef,
      activeStreamRequestIdRef,
      autoExpandTimeoutRef,
      prevSpecialistTypesRef,
      prevTileTypesRef,
      prevTripInputsRef,
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
      queueCompletionScroll,
    ]
  );

  return { executeStream };
}
