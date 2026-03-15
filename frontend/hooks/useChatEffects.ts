'use client';

/**
 * useChatEffects — side-effect orchestration for ChatPanel.
 *
 * Groups all useEffect blocks that are NOT related to scrolling
 * (those live in useChatScrolling). This hook is fire-and-forget:
 * it takes in all values the effects depend on and returns nothing.
 */

import { useEffect, useRef } from 'react';

import type { ActiveStatus } from '@/components/chat/SmartLoader';
import type { ChatMessage } from '@/types/chat';

// "Agency Voice" - Translates technical backend labels to travel concierge terminology
const AGENT_VOCAB: Record<string, string> = {
  ROUTING: 'CONSULTING',
  VALIDATING: 'VERIFYING',
  CHECKING: 'REVIEWING',
  FETCHING: 'SEARCHING',
  GENERATING: 'DRAFTING',
  READING: 'REVIEWING',
  WRITING: 'DRAFTING',
  CONSTRAINTS: 'LOGISTICS',
  MESSAGE: 'REQUEST',
  RESPONSE: 'ITINERARY',
};

const toAgencyVoice = (rawLabel: string): string => {
  let text = rawLabel.toUpperCase();
  Object.entries(AGENT_VOCAB).forEach(([tech, agency]) => {
    text = text.replace(new RegExp(tech, 'g'), agency);
  });
  return text;
};

// ID prefix for "ready to generate" messages that should be replaced when branches are created
const READY_MESSAGE_ID_PREFIX = 'ready_';

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

interface UseChatEffectsParams {
  // Loading / streaming state
  isLoading: boolean;
  isLoadingHistory: boolean;
  messages: ChatMessage[];

  // Scroll helpers (from useChatScrolling)
  scrollToBottom: (force?: boolean) => void;
  scrollPanelIntoView: () => void;

  // Input focus ref
  inputRef: React.RefObject<HTMLTextAreaElement | null>;

  // Ready-to-generate state
  readyToGenerate?: boolean;
  hasBranches?: boolean;
  generateTriggered: boolean;
  setGenerateTriggered: (v: boolean) => void;

  // Chat store actions
  loadHistory: () => void;
  filterMessages: (predicate: (msg: ChatMessage) => boolean) => void;

  // Node status -> Smart Loader
  nodeStatus: NodeStatus | null;
  setActiveStatus: React.Dispatch<React.SetStateAction<ActiveStatus | null>>;

  // Timeout refs for cleanup (owned by ChatPanel, cleaned here)
  autoExpandTimeoutRef: React.MutableRefObject<NodeJS.Timeout | null>;
  focusTimeoutRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>;
}

export function useChatEffects(params: UseChatEffectsParams): void {
  const {
    isLoading,
    isLoadingHistory,
    messages,
    scrollToBottom,
    scrollPanelIntoView,
    inputRef,
    readyToGenerate,
    hasBranches,
    generateTriggered,
    setGenerateTriggered,
    loadHistory,
    filterMessages,
    nodeStatus,
    setActiveStatus,
    autoExpandTimeoutRef,
    focusTimeoutRef,
  } = params;

  const prevIsLoadingRef = useRef(false);
  const readyMessageShownRef = useRef(false);

  // Scroll panel into view and focus input when response finishes (isLoading: true -> false)
  useEffect(() => {
    if (!prevIsLoadingRef.current && isLoading) {
      // Scroll to bottom when loading STARTS so Logic Terminal is visible
      requestAnimationFrame(() => {
        scrollToBottom(true);
        scrollPanelIntoView();
      });
    } else if (prevIsLoadingRef.current && !isLoading) {
      // Reset and force scroll to bottom when response finishes.
      // Late layout shifts are handled inside useChatScrolling's settle passes.
      scrollToBottom(true);
      scrollPanelIntoView();
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }
    prevIsLoadingRef.current = isLoading;
  }, [isLoading, scrollToBottom, scrollPanelIntoView, inputRef]);

  // Cleanup timeouts on unmount
  useEffect(() => {
    const autoExpand = autoExpandTimeoutRef;
    const focus = focusTimeoutRef;
    return () => {
      if (autoExpand.current) {
        clearTimeout(autoExpand.current);
      }
      if (focus.current) {
        clearTimeout(focus.current);
      }
    };
  }, [autoExpandTimeoutRef, focusTimeoutRef]);

  // Scroll to bottom when messages change (during streaming or new messages)
  useEffect(() => {
    if (messages.length > 0 && !isLoadingHistory) {
      scrollToBottom();
    }
  }, [messages.length, isLoadingHistory, scrollToBottom]);

  // Reset scroll tracking when user sends a message (starts loading)
  // Note: isUserScrolledUpRef is managed inside useChatScrolling via scrollToBottom(true)
  // This effect is kept for the explicit reset intent when loading starts.

  // Load chat history from store (only loads once, persists across remounts)
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, [inputRef]);

  // Reset generate-related state when readyToGenerate becomes false
  useEffect(() => {
    if (!readyToGenerate) {
      setGenerateTriggered(false);
      filterMessages((msg) => !msg.id.startsWith(READY_MESSAGE_ID_PREFIX));
    }
  }, [readyToGenerate, filterMessages, setGenerateTriggered]);

  // Ready-to-generate message tracking (backend sends the message via streaming)
  useEffect(() => {
    if (
      readyToGenerate &&
      !readyMessageShownRef.current &&
      !hasBranches &&
      !generateTriggered
    ) {
      readyMessageShownRef.current = true;
    }
    if (!readyToGenerate) {
      readyMessageShownRef.current = false;
    }
  }, [readyToGenerate, hasBranches, generateTriggered]);

  // Smart Loader: Single mutating status line (DS Section 19.C)
  useEffect(() => {
    if (!nodeStatus || !isLoading) return;

    if (nodeStatus.node === 'logic_reveal') {
      setActiveStatus((prev) =>
        prev
          ? {
              ...prev,
              detail: toAgencyVoice(nodeStatus.label),
            }
          : null
      );
      return;
    }

    setActiveStatus({
      label: toAgencyVoice(nodeStatus.label.replace(/\.+$/, '')),
      icon_key: nodeStatus.iconKey || 'default',
      detail: undefined,
    });
  }, [nodeStatus, isLoading, setActiveStatus]);
}
