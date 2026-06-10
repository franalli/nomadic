'use client';

/**
 * useChatSend — message-sending orchestration for ChatPanel.
 *
 * Owns sendMessageCore, handleSubmit, addAssistantMessage, burst-guard
 * refs, suggestion state, and streaming state (isLoading, streamingMessageId).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { getSendBurstGuardReason } from '@/components/chat/ChatPanel';
import { useActionLoader } from '@/hooks/useActionLoader';
import { type ChatSseRefs, useChatSse } from '@/hooks/useChatSse';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { type SSEFeasibilityWarningEvent, type streamGraphPlan } from '@/lib/api-streaming';
import { debugLog } from '@/lib/debug';
import { claimActiveTab, isActiveTab } from '@/lib/tabGuard';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { nextEnvelopeBufferGeneration, useDocumentStore } from '@/state/documentStore';
import type { ChatMessage } from '@/types/chat';
import type {
  DocumentBranch,
  DocumentTripInputs,
  GraphPlanResponse,
  SuggestionChip,
  SuggestionChipMeta,
} from '@/types/document';
import type { TriggerContext } from '@/types/loader';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import {
  buildMessageSignature,
  buildOptimisticExtensionPreview,
  buildSendRequestId,
  didOptimisticExtensionRegress,
  shouldStartPlanGeneration,
  waitForPendingMutationsToSettle,
} from './chatSendHelpers';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UseChatSendParams {
  // Callbacks from ChatPanel props
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: DocumentBranch[];
    tiles: Record<string, Tile>;
    primaryBranchId: string | null;
    tripInputs?: DocumentTripInputs | null;
    readyToGenerate?: boolean;
    response?: GraphPlanResponse;
  }) => void;
  onGeneratePlanStart?: () => void;
  onAutoExpandItinerary?: (options?: { forceFullRebuild?: boolean }) => void;
  onUserMessageSubmit?: (message: string) => void;
  selectedBranchId: string | null;
  hasBranches?: boolean;
  readyToGenerate?: boolean;

  // External state setters
  setGenerateTriggered: (v: boolean) => void;
  setActiveStatus: React.Dispatch<React.SetStateAction<import('@/components/chat/SmartLoader').ActiveStatus | null>>;

  // Scroll helpers (from useChatScrolling)
  scrollPanelIntoView: () => void;
  scrollToBottom: (force?: boolean) => void;

  // Input ref for focus management
  inputRef: React.RefObject<HTMLTextAreaElement | null>;

  // Toast
  toast: (message: string) => void;
}

export interface UseChatSendResult {
  // State
  isLoading: boolean;
  streamingMessageId: string | null;
  hasReceivedFirstToken: boolean;
  nodeStatus: NodeStatus | null;
  suggestedResponses: string[];
  suggestedResponseMeta: SuggestionChipMeta[];
  suggestionChips: SuggestionChip[];
  lastUserMessage: string | null;
  triggerContext: TriggerContext | null;

  // Loader hooks (exposed for JSX binding)
  delayedLoader: ReturnType<typeof useDelayedLoader>;
  actionLoader: ReturnType<typeof useActionLoader>;

  // Refs needed by ChatPanel
  isSendingRef: React.MutableRefObject<boolean>;
  autoExpandTimeoutRef: React.MutableRefObject<NodeJS.Timeout | null>;
  abortStreamRef: React.MutableRefObject<(() => void) | null>;
  focusTimeoutRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>;

  // Functions
  sendMessageCore: (messageText: string, options?: { suggestionClicked?: string }) => Promise<void>;
  addAssistantMessage: (message: string) => void;
  handleSubmit: (e: React.FormEvent) => Promise<void>;
  handleStopStreaming: () => void;

  // For ChatPanel to bind input state
  input: string;
  setInput: (v: string) => void;
}

interface NodeStatus {
  active: boolean;
  node: string;
  label: string;
  iconKey: string;
  estimatedDurationMs: number;
  startTime: number;
  stage?: number;
  topic?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useChatSend(params: UseChatSendParams): UseChatSendResult {
  const {
    onPlanResult,
    onGeneratePlanStart,
    onAutoExpandItinerary,
    onUserMessageSubmit,
    selectedBranchId,
    hasBranches,
    readyToGenerate,
    setGenerateTriggered,
    setActiveStatus,
    scrollPanelIntoView,
    scrollToBottom,
    inputRef,
    toast,
  } = params;

  // Chat store selectors
  const { addMessage, updateMessage, appendToMessage, updateMessageId, filterMessages } =
    useChatStore(
      useShallow((s) => ({
        addMessage: s.addMessage,
        updateMessage: s.updateMessage,
        appendToMessage: s.appendToMessage,
        updateMessageId: s.updateMessageId,
        filterMessages: s.filterMessages,
      }))
    );
  const sessionState = useChatStore((s) => s.sessionState);
  const setSessionState = useChatStore((s) => s.setSessionState);

  // Local state
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  // Keep ref in sync for use in callbacks without dep-array churn
  const streamingMessageIdRef = useRef(streamingMessageId);
  streamingMessageIdRef.current = streamingMessageId;
  // Mirror isLoading into a ref so sendMessageCore (which deliberately omits
  // isLoading from its deps) can read the *current* loading state to detect a
  // stranded send lock without re-creating the callback on every render.
  const isLoadingRef = useRef(isLoading);
  isLoadingRef.current = isLoading;
  const [hasReceivedFirstToken, setHasReceivedFirstToken] = useState(false);
  const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
  const [suggestedResponseMeta, setSuggestedResponseMeta] = useState<SuggestionChipMeta[]>([]);
  const [suggestionChips, setSuggestionChips] = useState<SuggestionChip[]>([]);
  const [lastUserMessage, setLastUserMessage] = useState<string | null>(null);
  const [nodeStatus, setNodeStatus] = useState<NodeStatus | null>(null);
  const [triggerContext, setTriggerContext] = useState<TriggerContext | null>(null);

  // Refs
  const sendMessageCoreRef = useRef<(msg: string) => void>(() => {});
  const isSendingRef = useRef(false);
  const lastMessageSentAtRef = useRef(0);
  const lastGenerateClickedAtRef = useRef(0);
  const abortStreamRef = useRef<(() => void) | null>(null);
  const activeStreamRequestIdRef = useRef<string | null>(null);
  const autoExpandTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const focusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingOptimisticRollbackRef = useRef<(() => void) | null>(null);
  const prevSpecialistTypesRef = useRef<Set<string>>(new Set());
  const prevTileTypesRef = useRef<Set<string>>(new Set());
  const prevTripInputsRef = useRef<{
    start_date: string | null;
    end_date: string | null;
    adults: number | null;
    children: number | null;
    budget: number | null;
    origin: string | null;
  } | null>(null);
  const recentSendSignatureRef = useRef<{ signature: string; ts: number } | null>(null);
  const envelopeGenerationRef = useRef(0);

  // Mirrors for the document→local suggestion sync effect below (read current
  // local values without putting them in the effect's dep array).
  const suggestionChipsRef = useRef(suggestionChips);
  suggestionChipsRef.current = suggestionChips;
  const suggestedResponsesRef = useRef(suggestedResponses);
  suggestedResponsesRef.current = suggestedResponses;
  const suggestedResponseMetaRef = useRef(suggestedResponseMeta);
  suggestedResponseMetaRef.current = suggestedResponseMeta;

  // Document chip fields (reactive). The backend persists these after every
  // chat turn and expand-itinerary regenerates them post-build — the document
  // is the SSoT for suggestion chips.
  const docChipFields = useDocumentStore(
    useShallow((s) => ({
      hasDocument: s.document !== null,
      chips: s.document?.suggestion_chips,
      responses: s.document?.suggested_responses,
      meta: s.document?.suggested_response_meta,
    }))
  );

  // ── Document → local suggestion sync ───────────────────────────────────────
  // One mechanism for BOTH reload hydration (fetchDocument) and post-mutation
  // refresh (PATCH merges, expand-itinerary done). Coexists with the SSE
  // complete path: setFromPlanResponse stores the same array references the
  // SSE handler sets locally, so the reference guard skips that turn.
  useEffect(() => {
    // Never fight an in-flight send — chips are cleared at send start and the
    // SSE complete handler repopulates them. A mid-send document update is
    // picked up when isLoading flips back to false (it's in the dep array).
    if (isSendingRef.current || isLoading) return;
    const { hasDocument, chips, responses, meta } = docChipFields;
    if (!hasDocument) {
      // RESET: document cleared → clear local suggestion state too.
      if (
        suggestionChipsRef.current.length > 0 ||
        suggestedResponsesRef.current.length > 0 ||
        suggestedResponseMetaRef.current.length > 0
      ) {
        setSuggestionChips([]);
        setSuggestedResponses([]);
        setSuggestedResponseMeta([]);
      }
      return;
    }
    // Reference guard: the SSE path already set this exact array locally.
    if (chips !== undefined && chips === suggestionChipsRef.current) return;

    const nextChips = chips ?? [];
    // The rendering gate keys off suggestedResponses — when the document
    // carries chips without suggested_responses, derive them from chip messages.
    const nextResponses =
      responses && responses.length > 0
        ? responses
        : nextChips.map((chip) => chip.message);
    const nextMeta = meta ?? [];
    if (
      nextChips.length === 0 &&
      nextResponses.length === 0 &&
      nextMeta.length === 0 &&
      suggestionChipsRef.current.length === 0 &&
      suggestedResponsesRef.current.length === 0 &&
      suggestedResponseMetaRef.current.length === 0
    ) {
      return; // Both sides already empty — avoid redundant state churn.
    }
    setSuggestionChips(nextChips);
    setSuggestedResponses(nextResponses);
    setSuggestedResponseMeta(nextMeta);
  }, [docChipFields, isLoading]);

  // Loader hooks
  const delayedLoader = useDelayedLoader({ showDelay: 400, etaThreshold: 600 });
  const actionLoader = useActionLoader({ showDelay: 400, minEtaThreshold: 600 });

  // SSE streaming hook
  const sseRefs: ChatSseRefs = {
    abortStreamRef,
    isSendingRef,
    activeStreamRequestIdRef,
    autoExpandTimeoutRef,
    prevSpecialistTypesRef,
    prevTileTypesRef,
    prevTripInputsRef,
  };

  const { executeStream } = useChatSse(sseRefs, {
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
    onFeasibilityWarning: useCallback((data: SSEFeasibilityWarningEvent['data']) => {
      if (data.status === 'infeasible' && data.reason) {
        toast(data.reason);
      }
    }, [toast]),
    onRetry: (msg: string) => sendMessageCoreRef.current(msg),
  });

  // Stop streaming when user clicks the stop button
  const handleStopStreaming = useCallback(() => {
    const rollbackOptimisticExtension = pendingOptimisticRollbackRef.current;
    pendingOptimisticRollbackRef.current = null;
    rollbackOptimisticExtension?.();

    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }
    if (autoExpandTimeoutRef.current) {
      clearTimeout(autoExpandTimeoutRef.current);
      autoExpandTimeoutRef.current = null;
    }
    activeStreamRequestIdRef.current = null;

    // Mark message as interrupted with a user-friendly message
    const currentStreamingId = streamingMessageIdRef.current;
    if (currentStreamingId) {
      const currentMsg = useChatStore.getState().messages.find((m) => m.id === currentStreamingId);
      const currentContent = (currentMsg?.content || '').trim();
      updateMessage(currentStreamingId, {
        content: currentContent + '\n\n*[Response stopped. You can continue the conversation or ask me to elaborate.]*',
      });
    }

    // Reset states
    setStreamingMessageId(null);
    setNodeStatus(null);
    setHasReceivedFirstToken(false);
    setIsLoading(false);
    setTriggerContext(null);
    isSendingRef.current = false;
    delayedLoader.reset();
    actionLoader.reset();

    // Clear SSE-set regeneration overlay (AbortError is swallowed by
    // streamGraphPlan so onComplete/onError won't fire to clean up).
    if (useDocumentStore.getState().isRegenerating) {
      useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
    }
  }, [updateMessage, delayedLoader, actionLoader]);

  const sendMessageCore = useCallback(
    async (
      messageText: string,
      options?: { suggestionClicked?: string; restoreInputOnBlock?: boolean }
    ) => {
      const trimmed = messageText.trim();
      const restoreDraftIfBlocked = () => {
        if (!options?.restoreInputOnBlock) return;
        setInput((current) => (current.length > 0 ? current : trimmed));
        requestAnimationFrame(() => {
          inputRef.current?.focus();
        });
      };
      if (!trimmed) {
        debugLog('[ChatPanel] Skipping - empty message');
        return;
      }

      // SYNC GUARD: Prevent duplicate sends (React StrictMode safe).
      //
      // SELF-HEAL: isSendingRef is a synchronous dedup latch that a send's
      // lifecycle (onComplete/onError/watchdog/finally) is responsible for
      // clearing. Those resets early-return on stale/superseded streams, so a
      // superseded turn can strand the latch `true` forever — after which this
      // guard silently drops EVERY future send (typed message AND chip click),
      // which presents as "the whole app is dead, nothing happens".
      //
      // A genuinely in-flight send keeps either an open stream connection
      // (abortStreamRef set) or the loading UI (isLoading true). If neither is
      // present while the latch is set, it is stranded — clear it and proceed
      // instead of dropping the send. This cannot start a concurrent stream
      // because a live stream always satisfies one of those two conditions.
      if (isSendingRef.current) {
        const sendActuallyInFlight =
          abortStreamRef.current !== null || isLoadingRef.current;
        if (sendActuallyInFlight) {
          debugLog('[ChatPanel] Skipping - already sending (ref guard)');
          restoreDraftIfBlocked();
          return;
        }
        debugLog('[ChatPanel] Clearing stranded send lock (no active stream)');
        isSendingRef.current = false;
      }

      // Abort any previous in-flight stream before starting a new one.
      // Prevents ghost duplicate requests from consuming LLM tokens.
      if (abortStreamRef.current) {
        const rollbackOptimisticExtension = pendingOptimisticRollbackRef.current;
        pendingOptimisticRollbackRef.current = null;
        rollbackOptimisticExtension?.();
        abortStreamRef.current();
        abortStreamRef.current = null;
        // Clean up orphaned partial assistant message from the aborted stream
        if (streamingMessageIdRef.current) {
          filterMessages((m) => m.id !== streamingMessageIdRef.current);
          setStreamingMessageId(null);
        }
      }

      const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER || trimmed.toLowerCase() === 'build plan';
      const now = Date.now();
      const requestId = buildSendRequestId(now);

      debugLog('[ChatPanel] sendMessageCore called', {
        message: trimmed.slice(0, 50),
        isGenerateTrigger,
        isSending: isSendingRef.current,
        request_id: requestId,
        destination: useDocumentStore.getState().document?.trip_inputs?.destination,
      });

      // Multi-tab guard (advisory)
      if (!isActiveTab()) {
        toast('This trip is being edited in another tab.');
        restoreDraftIfBlocked();
        return;
      }
      claimActiveTab();

      const guardReason = getSendBurstGuardReason({
        isGenerateTrigger,
        isLoading: isSendingRef.current,
        now,
        lastMessageSentAt: lastMessageSentAtRef.current,
        lastGenerateClickedAt: lastGenerateClickedAtRef.current,
      });
      if (guardReason) {
        restoreDraftIfBlocked();
        if (guardReason !== 'loading') {
          toast(guardReason);
        } else {
          debugLog('[ChatPanel] Skipping - loading');
        }
        return;
      }

      const documentSnapshot = useDocumentStore.getState().document;
      const tripInputsSnapshot = documentSnapshot?.trip_inputs;
      const optimisticExtension = buildOptimisticExtensionPreview(
        trimmed,
        tripInputsSnapshot,
        documentSnapshot?.day_cards
      );
      const optimisticRollbackDayCards =
        optimisticExtension && documentSnapshot?.day_cards
          ? (structuredClone(documentSnapshot.day_cards) as DayCard[])
          : null;
      const optimisticRollbackIsRegenerating = useDocumentStore.getState().isRegenerating;
      const rollbackOptimisticExtension = () => {
        pendingOptimisticRollbackRef.current = null;
        if (!optimisticExtension || !tripInputsSnapshot || !optimisticRollbackDayCards) {
          return;
        }
        const currentDoc = useDocumentStore.getState().document;
        if (!currentDoc?.trip_inputs) {
          return;
        }
        useDocumentStore.getState().mergeEnvelope(
          {
            trip_inputs: {
              ...currentDoc.trip_inputs,
              end_date: tripInputsSnapshot.end_date ?? null,
              trip_duration: tripInputsSnapshot.trip_duration ?? null,
            },
            day_cards: structuredClone(optimisticRollbackDayCards),
          },
          envelopeGenerationRef.current
        );
        useDocumentStore.getState().setRegenerationState({
          isRegenerating: optimisticRollbackIsRegenerating,
        });
      };
      const signature = buildMessageSignature(
        trimmed,
        selectedBranchId,
        tripInputsSnapshot,
        options?.suggestionClicked
      );
      const dedupeWindowMs = isGenerateTrigger ? 3500 : 1200;
      const lastSignature = recentSendSignatureRef.current;
      if (
        lastSignature &&
        lastSignature.signature === signature &&
        now - lastSignature.ts < dedupeWindowMs
      ) {
        debugLog('[ChatPanel] Skipping - duplicate send signature', {
          signature,
          ageMs: now - lastSignature.ts,
        });
        restoreDraftIfBlocked();
        return;
      }

      // Lock the send cycle before waiting on document mutations so a blocked send
      // cannot be followed by a second submit that later gets overwritten.
      setIsLoading(true);
      isSendingRef.current = true;

      // MUTATION GATE: Wait for in-flight mutations (fill-day, drag-drop) to settle.
      if (useDocumentStore.getState().hasPendingMutations()) {
        const mutationsSettled = await waitForPendingMutationsToSettle();
        if (!mutationsSettled) {
          setIsLoading(false);
          isSendingRef.current = false;
          restoreDraftIfBlocked();
          toast('Please wait for itinerary changes to finish, then try again.');
          return;
        }
      }
      const sendStartedAt = Date.now();
      if (isGenerateTrigger) {
        lastGenerateClickedAtRef.current = sendStartedAt;
      } else {
        lastMessageSentAtRef.current = sendStartedAt;
      }
      recentSendSignatureRef.current = { signature, ts: sendStartedAt };

      // Reset Smart Loader for new message
      setActiveStatus(null);
      if (autoExpandTimeoutRef.current) {
        clearTimeout(autoExpandTimeoutRef.current);
        autoExpandTimeoutRef.current = null;
      }

      const nextTriggerContext: TriggerContext = {
        isGeneratePlanTrigger: isGenerateTrigger,
        isConstraintChange: hasBranches && !isGenerateTrigger,
      };
      setTriggerContext(nextTriggerContext);

      if (isGenerateTrigger) {
        setGenerateTriggered(true);
      }

      if (
        shouldStartPlanGeneration({
          isGenerateTrigger,
          hasBranches,
          message: trimmed,
          readyToGenerate,
          tripInputs: tripInputsSnapshot,
        })
      ) {
        onGeneratePlanStart?.();
      }

      const isSilentPlanGeneration = isGenerateTrigger;

      const userMsgId = `u_${Date.now()}`;
      if (!isSilentPlanGeneration) {
        const userMessage: ChatMessage = {
          id: userMsgId,
          role: 'user',
          content: trimmed,
          classification: 'constraint',
        };
        addMessage(userMessage);
        onUserMessageSubmit?.(trimmed);
      }
      setSuggestedResponses([]);
      setSuggestedResponseMeta([]);
      setSuggestionChips([]);
      setLastUserMessage(trimmed);
      activeStreamRequestIdRef.current = requestId;

      const streamingMsgId = `a_stream_${Date.now()}`;
      if (!isSilentPlanGeneration) {
        addMessage({ id: streamingMsgId, role: 'assistant', content: '' });
        setStreamingMessageId(streamingMsgId);
        setHasReceivedFirstToken(false);
      }

      let streamStarted = false;
      try {
        envelopeGenerationRef.current = nextEnvelopeBufferGeneration();
        if (optimisticExtension) {
          useDocumentStore.getState().mergeEnvelope(
            {
              trip_inputs: optimisticExtension.tripInputs,
              day_cards: optimisticExtension.dayCards,
            },
            envelopeGenerationRef.current
          );
          pendingOptimisticRollbackRef.current = rollbackOptimisticExtension;
        }

        await useDocumentStore.getState().ensureSettingsFlushed({
          requestId,
          sendCycleId: requestId,
        });

        if (activeStreamRequestIdRef.current !== requestId || !isSendingRef.current) {
          rollbackOptimisticExtension();
          debugLog('[ChatPanel] Skipping stream start - send was cancelled before stream init', {
            request_id: requestId,
          });
          return;
        }

        const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;
        const requestTripInputs = (() => {
          if (!currentTripInputs) return currentTripInputs;
          if (!optimisticExtension || !tripInputsSnapshot) return currentTripInputs;
          return {
            ...currentTripInputs,
            end_date: tripInputsSnapshot.end_date ?? null,
            trip_duration: tripInputsSnapshot.trip_duration ?? null,
          };
        })();

        const normalizedTripInputs = (() => {
          if (!requestTripInputs) return requestTripInputs;
          const categories = requestTripInputs.activity_settings?.categories ?? [];
          if (categories.length > 0) return requestTripInputs;
          return {
            ...requestTripInputs,
            activity_settings: {
              ...(requestTripInputs.activity_settings ?? {}),
              categories: [],
              day_preferences: {},
            },
          };
        })();

        prevTripInputsRef.current = normalizedTripInputs ? {
          start_date: normalizedTripInputs.start_date ?? null,
          end_date: normalizedTripInputs.end_date ?? null,
          adults: normalizedTripInputs.adults ?? null,
          children: normalizedTripInputs.children ?? null,
          budget: normalizedTripInputs.budget ?? null,
          origin: normalizedTripInputs.origin ?? null,
        } : null;

        const body: Parameters<typeof streamGraphPlan>[0] = {
          message: trimmed,
          session_state: sessionState ?? undefined,
          suggestion_clicked: options?.suggestionClicked,
          trip_inputs: normalizedTripInputs ?? undefined,
        };

        if (isGenerateTrigger) {
          debugLog('[ChatPanel] Sending GENERATE_PLAN_TRIGGER to API', {
            destination: body.trip_inputs?.destination,
            start_date: body.trip_inputs?.start_date,
            end_date: body.trip_inputs?.end_date,
            hasTripInputs: !!body.trip_inputs,
          });
        }
        useDocumentStore.getState().bumpMessageSendNonce();

        streamStarted = true;
        const streamResult = await executeStream({
          body,
          requestId,
          streamingMsgId,
          isSilentPlanGeneration,
          selectedBranchId,
          envelopeGeneration: envelopeGenerationRef.current,
          triggerContext: nextTriggerContext,
          delayedLoader,
          actionLoader,
        });
        if (streamResult === 'complete') {
          pendingOptimisticRollbackRef.current = null;
          const currentDoc = useDocumentStore.getState().document;
          const currentTripInputs = currentDoc?.trip_inputs;
          if (
            currentTripInputs &&
            didOptimisticExtensionRegress(
              currentTripInputs,
              tripInputsSnapshot,
              optimisticExtension
            )
          ) {
            useDocumentStore.getState().mergeEnvelope(
              {
                trip_inputs: {
                  ...currentTripInputs,
                  end_date: optimisticExtension!.tripInputs.end_date ?? null,
                  trip_duration: optimisticExtension!.tripInputs.trip_duration ?? null,
                },
                day_cards:
                  (currentDoc?.day_cards?.length ?? 0) <= optimisticExtension!.dayCards.length
                    ? structuredClone(optimisticExtension!.dayCards)
                    : undefined,
              },
              envelopeGenerationRef.current
            );
          }
        }
        if (streamResult === 'error') {
          rollbackOptimisticExtension();
        }
      } catch (error) {
        console.error('Failed to initialize chat stream:', error);
        if (!streamStarted) {
          rollbackOptimisticExtension();
        }
        if (!isSilentPlanGeneration) {
          updateMessage(streamingMsgId, {
            content: 'Could not start this request. Please try again.',
          });
        } else {
          toast('Could not start this request. Please try again.');
        }
      } finally {
        // Release the send lock unless a *different* live request now owns the
        // pipeline. When activeStreamRequestIdRef is null nobody owns it, so it
        // is safe (and necessary) to clear the latch here — otherwise a stream
        // that resolved 'stale' would leave isSendingRef stranded `true`.
        if (
          !streamStarted ||
          activeStreamRequestIdRef.current === requestId ||
          activeStreamRequestIdRef.current === null
        ) {
          activeStreamRequestIdRef.current = null;
          setIsLoading(false);
          setTriggerContext(null);
          isSendingRef.current = false;
          if (!streamStarted) {
            setStreamingMessageId(null);
          }
        }
      }
    },
    [
      onGeneratePlanStart,
      selectedBranchId,
      sessionState,
      filterMessages,
      addMessage,
      delayedLoader,
      actionLoader,
      hasBranches,
      readyToGenerate,
      onUserMessageSubmit,
      toast,
      executeStream,
      inputRef,
      setActiveStatus,
      setGenerateTriggered,
      updateMessage,
      // streamingMessageId REMOVED — using ref instead
    ]
  );
  sendMessageCoreRef.current = sendMessageCore;

  const addAssistantMessage = useCallback((message: string) => {
    const assistantMessage: ChatMessage = {
      id: `a_ui_${Date.now()}`,
      role: 'assistant',
      content: message,
    };
    addMessage(assistantMessage);
    scrollPanelIntoView();
    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
  }, [scrollPanelIntoView, addMessage, inputRef]);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    setInput('');
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
    focusTimeoutRef.current = setTimeout(() => inputRef.current?.focus(), 0);
    await sendMessageCore(trimmed, { restoreInputOnBlock: true });
  }, [input, isLoading, inputRef, sendMessageCore]);

  return useMemo(() => ({
    // State
    isLoading,
    streamingMessageId,
    hasReceivedFirstToken,
    nodeStatus,
    suggestedResponses,
    suggestedResponseMeta,
    suggestionChips,
    lastUserMessage,
    triggerContext,

    // Loaders
    delayedLoader,
    actionLoader,

    // Refs
    isSendingRef,
    autoExpandTimeoutRef,
    abortStreamRef,
    focusTimeoutRef,

    // Functions
    sendMessageCore,
    addAssistantMessage,
    handleSubmit,
    handleStopStreaming,

    // Input state
    input,
    setInput,
  }), [
    isLoading, streamingMessageId, hasReceivedFirstToken, nodeStatus,
    suggestedResponses, suggestedResponseMeta, suggestionChips,
    lastUserMessage, triggerContext, delayedLoader, actionLoader,
    isSendingRef, autoExpandTimeoutRef, abortStreamRef, focusTimeoutRef,
    sendMessageCore, addAssistantMessage, handleSubmit, handleStopStreaming,
    input, setInput,
  ]);
}
