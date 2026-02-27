'use client';

/**
 * useChatSend — message-sending orchestration for ChatPanel.
 *
 * Owns sendMessageCore, handleSubmit, addAssistantMessage, burst-guard
 * refs, suggestion state, and streaming state (isLoading, streamingMessageId).
 */

import { useCallback, useRef, useState } from 'react';

import { getSendBurstGuardReason } from '@/components/chat/ChatPanel';
import { useActionLoader } from '@/hooks/useActionLoader';
import { type ChatSseRefs, useChatSse } from '@/hooks/useChatSse';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { type streamGraphPlan } from '@/lib/api';
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

  // External state setters
  setGenerateTriggered: (v: boolean) => void;
  setActiveStatus: React.Dispatch<React.SetStateAction<import('@/components/chat/SmartLoader').ActiveStatus | null>>;

  // Scroll helpers (from useChatScrolling)
  scrollPanelIntoView: () => void;

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
    setGenerateTriggered,
    setActiveStatus,
    scrollPanelIntoView,
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
  });

  // Stop streaming when user clicks the stop button
  const handleStopStreaming = useCallback(() => {
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
    if (streamingMessageId) {
      const currentMsg = useChatStore.getState().messages.find((m) => m.id === streamingMessageId);
      const currentContent = (currentMsg?.content || '').trim();
      updateMessage(streamingMessageId, {
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
  }, [streamingMessageId, updateMessage, delayedLoader, actionLoader]);

  const sendMessageCore = useCallback(
    async (messageText: string, options?: { suggestionClicked?: string }) => {
      const trimmed = messageText.trim();
      if (!trimmed) {
        debugLog('[ChatPanel] Skipping - empty message');
        return;
      }

      // SYNC GUARD: Prevent duplicate sends (React StrictMode safe)
      if (isSendingRef.current) {
        debugLog('[ChatPanel] Skipping - already sending (ref guard)');
        return;
      }

      // MUTATION GATE: Wait for in-flight mutations (fill-day, drag-drop) to settle.
      if (useDocumentStore.getState().hasPendingMutations()) {
        await new Promise<void>((resolve) => {
          let settled = false;
          const settle = () => {
            if (settled) return;
            settled = true;
            clearTimeout(timeout);
            unsub();
            resolve();
          };
          const timeout = setTimeout(settle, 5_000);
          const unsub = useDocumentStore.subscribe((state) => {
            if (!state.hasPendingMutations()) settle();
          });
          // Close race window between outer check and subscribe
          if (!useDocumentStore.getState().hasPendingMutations()) settle();
        });
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
        if (guardReason !== 'loading') {
          toast(guardReason);
        } else {
          debugLog('[ChatPanel] Skipping - loading');
        }
        return;
      }
      if (isGenerateTrigger) {
        lastGenerateClickedAtRef.current = now;
      } else {
        lastMessageSentAtRef.current = now;
      }

      const tripInputsSnapshot = useDocumentStore.getState().document?.trip_inputs;
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
        return;
      }
      recentSendSignatureRef.current = { signature, ts: now };

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
      setIsLoading(true);
      isSendingRef.current = true;
      activeStreamRequestIdRef.current = requestId;

      const streamingMsgId = `a_stream_${Date.now()}`;
      if (!isSilentPlanGeneration) {
        addMessage({ id: streamingMsgId, role: 'assistant', content: '' });
        setStreamingMessageId(streamingMsgId);
        setHasReceivedFirstToken(false);
      }

      let streamStarted = false;
      try {
        await useDocumentStore.getState().ensureSettingsFlushed({
          requestId,
          sendCycleId: requestId,
        });

        if (activeStreamRequestIdRef.current !== requestId || !isSendingRef.current) {
          debugLog('[ChatPanel] Skipping stream start - send was cancelled before stream init', {
            request_id: requestId,
          });
          return;
        }

        const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;
        const normalizedTripInputs = (() => {
          if (!currentTripInputs) return currentTripInputs;
          const categories = currentTripInputs.activity_settings?.categories ?? [];
          if (categories.length > 0) return currentTripInputs;
          return {
            ...currentTripInputs,
            activity_settings: {
              ...(currentTripInputs.activity_settings ?? {}),
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
        envelopeGenerationRef.current = nextEnvelopeBufferGeneration();

        streamStarted = true;
        await executeStream({
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
      } catch (error) {
        console.error('Failed to initialize chat stream:', error);
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
    [onGeneratePlanStart, selectedBranchId, sessionState, addMessage, delayedLoader, actionLoader, hasBranches, onUserMessageSubmit, toast, executeStream, setActiveStatus, setGenerateTriggered, updateMessage]
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
    await sendMessageCore(trimmed);
  }, [input, isLoading, inputRef, sendMessageCore]);

  return {
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
  };
}
