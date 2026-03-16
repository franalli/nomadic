'use client';

/**
 * useChatSend — message-sending orchestration for ChatPanel.
 *
 * Owns sendMessageCore, handleSubmit, addAssistantMessage, burst-guard
 * refs, suggestion state, and streaming state (isLoading, streamingMessageId).
 */

import { useCallback, useMemo, useRef, useState } from 'react';

import { getSendBurstGuardReason } from '@/components/chat/ChatPanel';
import { useActionLoader } from '@/hooks/useActionLoader';
import { type ChatSseRefs, useChatSse } from '@/hooks/useChatSse';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { type SSEFeasibilityWarningEvent, type streamGraphPlan } from '@/lib/api';
import { parseISODateLocal } from '@/lib/date-utils';
import { debugLog } from '@/lib/debug';
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

function buildSendRequestId(now: number): string {
  return `req_${now}_${Math.random().toString(36).slice(2, 8)}`;
}

function buildMessageSignature(
  message: string,
  selectedBranchId: string | null,
  tripInputs: DocumentTripInputs | null | undefined,
  suggestionClicked?: string
): string {
  return JSON.stringify({
    m: message.trim().toLowerCase(),
    s: suggestionClicked?.trim().toLowerCase() ?? null,
    b: selectedBranchId,
    d: tripInputs?.destination ?? null,
    sd: tripInputs?.start_date ?? null,
    ed: tripInputs?.end_date ?? null,
    a: tripInputs?.adults ?? null,
    c: tripInputs?.children ?? null,
    o: tripInputs?.origin ?? null,
    bg: tripInputs?.budget ?? null,
  });
}

const EXTEND_BY_DAYS_PATTERN = /^(?:please\s+)?extend(?:\s+by)?\s+(\d+)\s+days?$/i;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

function formatISODateLocal(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function parseDateExtensionDays(message: string): number | null {
  const match = message.trim().match(EXTEND_BY_DAYS_PATTERN);
  if (!match) return null;
  const parsed = Number.parseInt(match[1] ?? '', 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function computeInclusiveTripDays(startDate: Date, endDate: Date): number {
  const startUtc = Date.UTC(startDate.getFullYear(), startDate.getMonth(), startDate.getDate());
  const endUtc = Date.UTC(endDate.getFullYear(), endDate.getMonth(), endDate.getDate());
  return Math.floor((endUtc - startUtc) / MS_PER_DAY) + 1;
}

function buildOptimisticExtensionPreview(
  message: string,
  tripInputs: DocumentTripInputs | null | undefined,
  dayCards: DayCard[] | undefined
): { tripInputs: DocumentTripInputs; dayCards: DayCard[] } | null {
  const extensionDays = parseDateExtensionDays(message);
  if (!extensionDays || !tripInputs?.start_date || !tripInputs.end_date || !dayCards?.length) {
    return null;
  }

  const startDate = parseISODateLocal(tripInputs.start_date);
  const currentEndDate = parseISODateLocal(tripInputs.end_date);
  if (!startDate || !currentEndDate) {
    return null;
  }

  const nextEndDate = new Date(currentEndDate.getTime());
  nextEndDate.setDate(nextEndDate.getDate() + extensionDays);

  const totalDays = computeInclusiveTripDays(startDate, nextEndDate);
  if (totalDays <= dayCards.length) {
    return null;
  }

  const optimisticDayCards = structuredClone(dayCards) as DayCard[];
  for (let dayNumber = optimisticDayCards.length + 1; dayNumber <= totalDays; dayNumber += 1) {
    const dayDate = new Date(startDate.getTime());
    dayDate.setDate(startDate.getDate() + dayNumber - 1);
    optimisticDayCards.push({
      day_number: dayNumber,
      date: formatISODateLocal(dayDate),
      label: 'Planning in progress',
      blocks: [
        {
          period: 'morning',
          activity_type: 'planning_placeholder',
          summary: `Planning Day ${dayNumber}...`,
          is_skeleton: true,
        },
      ],
    });
  }

  return {
    tripInputs: {
      ...tripInputs,
      end_date: formatISODateLocal(nextEndDate),
      trip_duration: totalDays,
    },
    dayCards: optimisticDayCards,
  };
}

function didOptimisticExtensionRegress(
  currentTripInputs: DocumentTripInputs | null | undefined,
  previousTripInputs: DocumentTripInputs | null | undefined,
  optimisticExtension: { tripInputs: DocumentTripInputs; dayCards: DayCard[] } | null
): boolean {
  if (!currentTripInputs || !previousTripInputs || !optimisticExtension) {
    return false;
  }

  const previousEndDate = previousTripInputs.end_date;
  const optimisticEndDate = optimisticExtension.tripInputs.end_date;
  const currentEndDate = currentTripInputs.end_date;
  if (!previousEndDate || !optimisticEndDate || !currentEndDate) {
    return false;
  }

  const previousEnd = parseISODateLocal(previousEndDate);
  const optimisticEnd = parseISODateLocal(optimisticEndDate);
  const currentEnd = parseISODateLocal(currentEndDate);
  if (!previousEnd || !optimisticEnd || !currentEnd) {
    return false;
  }

  if (optimisticEnd.getTime() <= previousEnd.getTime()) {
    return false;
  }

  return currentEnd.getTime() <= previousEnd.getTime();
}

function shouldStartPlanGeneration({
  isGenerateTrigger,
  hasBranches,
  message,
  readyToGenerate,
  tripInputs,
}: {
  isGenerateTrigger: boolean;
  hasBranches?: boolean;
  message: string;
  readyToGenerate?: boolean;
  tripInputs: DocumentTripInputs | null | undefined;
}): boolean {
  if (isGenerateTrigger) return true;
  if (readyToGenerate === true) return true;
  if (hasBranches) return false;

  const normalized = message.trim().toLowerCase();
  const hasDateCue =
    /\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*-\s*\d{1,2}(?:st|nd|rd|th)?)?|this weekend|next weekend|long weekend)\b/i.test(
      normalized
    );
  if (!hasDateCue) return false;

  if (tripInputs?.destination) return true;
  if (/\bfrom\b/.test(normalized)) return true;
  if (
    /\b(?:trip|travel|vacation|holiday|getaway|itinerary|plan|hotel|stay|flight)\b/.test(
      normalized
    )
  ) {
    return true;
  }

  return normalized.split(/\s+/).filter(Boolean).length >= 4;
}

function waitForPendingMutationsToSettle(timeoutMs = 5_000): Promise<boolean> {
  if (!useDocumentStore.getState().hasPendingMutations()) {
    return Promise.resolve(true);
  }

  return new Promise<boolean>((resolve) => {
    let settled = false;
    let unsubscribe: (() => void) | null = null;

    const settle = (ready: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      unsubscribe?.();
      resolve(ready);
    };

    const timeout = setTimeout(() => settle(false), timeoutMs);
    unsubscribe = useDocumentStore.subscribe((state, prev) => {
      if (state._pendingMutations !== prev._pendingMutations && !state.hasPendingMutations()) {
        settle(true);
      }
    });

    if (!useDocumentStore.getState().hasPendingMutations()) {
      settle(true);
    }
  });
}

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
  const addMessage = useChatStore((s) => s.addMessage);
  const updateMessage = useChatStore((s) => s.updateMessage);
  const appendToMessage = useChatStore((s) => s.appendToMessage);
  const updateMessageId = useChatStore((s) => s.updateMessageId);
  const filterMessages = useChatStore((s) => s.filterMessages);
  const sessionState = useChatStore((s) => s.sessionState);
  const setSessionState = useChatStore((s) => s.setSessionState);

  // Local state
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  // Keep ref in sync for use in callbacks without dep-array churn
  const streamingMessageIdRef = useRef(streamingMessageId);
  streamingMessageIdRef.current = streamingMessageId;
  const [hasReceivedFirstToken, setHasReceivedFirstToken] = useState(false);
  const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
  const [suggestedResponseMeta, setSuggestedResponseMeta] = useState<SuggestionChipMeta[]>([]);
  const [suggestionChips, setSuggestionChips] = useState<SuggestionChip[]>([]);
  const [lastUserMessage, setLastUserMessage] = useState<string | null>(null);
  const [nodeStatus, setNodeStatus] = useState<NodeStatus | null>(null);
  const [triggerContext, setTriggerContext] = useState<TriggerContext | null>(null);

  // Refs
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

      // SYNC GUARD: Prevent duplicate sends (React StrictMode safe)
      if (isSendingRef.current) {
        debugLog('[ChatPanel] Skipping - already sending (ref guard)');
        restoreDraftIfBlocked();
        return;
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
        if (!streamStarted || activeStreamRequestIdRef.current === requestId) {
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
