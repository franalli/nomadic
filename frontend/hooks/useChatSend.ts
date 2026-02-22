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
import { useDocumentStore } from '@/state/documentStore';
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
  lastUserMsgIdRef: React.MutableRefObject<string | null>;
  lastSystemEventIdRef: React.MutableRefObject<string | null>;
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
  const autoExpandTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const focusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastUserMsgIdRef = useRef<string | null>(null);
  const lastSystemEventIdRef = useRef<string | null>(null);
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

  // Loader hooks
  const delayedLoader = useDelayedLoader({ showDelay: 400, etaThreshold: 600 });
  const actionLoader = useActionLoader({ showDelay: 400, minEtaThreshold: 600 });

  // SSE streaming hook
  const sseRefs: ChatSseRefs = {
    abortStreamRef,
    isSendingRef,
    autoExpandTimeoutRef,
    prevSpecialistTypesRef,
    prevTileTypesRef,
    prevTripInputsRef,
    lastUserMsgIdRef,
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
    isSendingRef.current = false;
    delayedLoader.reset();
  }, [streamingMessageId, updateMessage, delayedLoader]);

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

      // MUTATION GATE: Wait for in-flight mutations (fill-day, drag-drop) to settle
      if (useDocumentStore.getState().hasPendingMutations()) {
        const maxWait = 10_000;
        const poll = 100;
        const start = Date.now();
        while (useDocumentStore.getState().hasPendingMutations() && Date.now() - start < maxWait) {
          await new Promise(r => setTimeout(r, poll));
        }
      }

      const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER || trimmed.toLowerCase() === 'build plan';
      const now = Date.now();
      const requestId = buildSendRequestId(now);

      debugLog('[ChatPanel] sendMessageCore called', {
        message: trimmed.slice(0, 50),
        isGenerateTrigger,
        isLoading,
        request_id: requestId,
        destination: useDocumentStore.getState().document?.trip_inputs?.destination,
      });

      const guardReason = getSendBurstGuardReason({
        isGenerateTrigger,
        isLoading,
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

      if (isLoading) {
        debugLog('[ChatPanel] Skipping - loading');
        return;
      }

      // Reset Smart Loader for new message
      setActiveStatus(null);

      setTriggerContext({
        isGeneratePlanTrigger: isGenerateTrigger,
        isConstraintChange: hasBranches && !isGenerateTrigger,
      });

      if (isGenerateTrigger) {
        setGenerateTriggered(true);
        onGeneratePlanStart?.();
      }

      const isSilentPlanGeneration = isGenerateTrigger;

      const userMsgId = `u_${Date.now()}`;
      if (isGenerateTrigger && !isSilentPlanGeneration) {
        const systemEventId = `sys_${Date.now()}`;
        addMessage({
          id: systemEventId,
          role: 'system',
          content: '',
          displayMode: 'ack_line',
          ackStatus: 'pending',
        });
        lastSystemEventIdRef.current = systemEventId;
      } else if (!isSilentPlanGeneration) {
        const userMessage: ChatMessage = {
          id: userMsgId,
          role: 'user',
          content: trimmed,
          classification: 'constraint',
          ackStatus: 'pending',
        };
        addMessage(userMessage);
        lastUserMsgIdRef.current = userMsgId;
        onUserMessageSubmit?.(trimmed);
      }
      setSuggestedResponses([]);
      setSuggestedResponseMeta([]);
      setSuggestionChips([]);
      setLastUserMessage(trimmed);
      setIsLoading(true);
      isSendingRef.current = true;

      const streamingMsgId = `a_stream_${Date.now()}`;
      if (!isSilentPlanGeneration) {
        addMessage({ id: streamingMsgId, role: 'assistant', content: '' });
        setStreamingMessageId(streamingMsgId);
        setHasReceivedFirstToken(false);
      }

      await useDocumentStore.getState().ensureSettingsFlushed({
        requestId,
        sendCycleId: requestId,
      });

      const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;

      prevTripInputsRef.current = currentTripInputs ? {
        start_date: currentTripInputs.start_date ?? null,
        end_date: currentTripInputs.end_date ?? null,
        adults: currentTripInputs.adults ?? null,
        children: currentTripInputs.children ?? null,
        budget: currentTripInputs.budget ?? null,
        origin: currentTripInputs.origin ?? null,
      } : null;

      const body: Parameters<typeof streamGraphPlan>[0] = {
        message: trimmed,
        session_state: sessionState ?? undefined,
        suggestion_clicked: options?.suggestionClicked,
        trip_inputs: currentTripInputs ?? undefined,
      };

      if (isGenerateTrigger) {
        debugLog('[ChatPanel] Sending GENERATE_PLAN_TRIGGER to API', {
          destination: body.trip_inputs?.destination,
          start_date: body.trip_inputs?.start_date,
          end_date: body.trip_inputs?.end_date,
          hasTripInputs: !!body.trip_inputs,
        });
      }

      await executeStream({
        body,
        streamingMsgId,
        isSilentPlanGeneration,
        selectedBranchId,
        triggerContext,
        delayedLoader,
        actionLoader,
      });
    },
    [isLoading, onGeneratePlanStart, selectedBranchId, sessionState, addMessage, delayedLoader, actionLoader, triggerContext, hasBranches, onUserMessageSubmit, toast, executeStream, setActiveStatus, setGenerateTriggered]
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
    lastUserMsgIdRef,
    lastSystemEventIdRef,
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
