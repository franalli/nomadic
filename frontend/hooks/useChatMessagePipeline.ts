'use client';

import { useMemo } from 'react';

import {
  buildVisibleMessages,
  EMPTY_VISIBLE_MESSAGES,
  sanitizeContent,
} from '@/components/chat/chatMessageProcessing';
import type { VisibleMessage } from '@/components/chat/ChatMessageRenderer';
import { useChatStore } from '@/state/chatStore';
import type { ChatMessage } from '@/types/chat';

/**
 * useChatMessagePipeline — 6-step memoized derivation chain that transforms
 * raw chat messages into the VisibleMessage[] array consumed by ChatMessageList.
 *
 * Steps:
 * 1. stableFingerprint — comma-joined IDs of non-streaming messages
 * 2. stableMessages — filtered from store (one-shot .getState(), not subscription)
 * 3. visibleStable — buildVisibleMessages()
 * 4. streamingMessage — find by ID
 * 5. streamingVisible — sanitizeContent()
 * 6. visibleMessages — concat stable + streaming
 */
export function useChatMessagePipeline(
  messages: ChatMessage[],
  streamingMessageId: string | null,
  isGenerating: boolean,
  hasBranches: boolean,
): VisibleMessage[] {
  // Build a fingerprint of non-streaming message IDs so the filtered
  // array keeps stable identity when only streaming tokens change —
  // prevents downstream visibleStable recomputation on each token.
  const stableFingerprint = useMemo(() => {
    const ids: string[] = [];
    for (const m of messages) {
      if (m.id !== streamingMessageId) ids.push(m.id);
    }
    return ids.join(',');
  }, [messages, streamingMessageId]);

  const stableMessages = useMemo(
    () => useChatStore.getState().messages.filter((m) => m.id !== streamingMessageId),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fingerprint is the semantic dep; store.getState() reads live data
    [stableFingerprint],
  );
  const visibleStable = useMemo(
    () => buildVisibleMessages(stableMessages, isGenerating, hasBranches),
    [stableMessages, isGenerating, hasBranches],
  );

  const streamingMessage = useMemo(
    () => messages.find((m) => m.id === streamingMessageId) ?? null,
    [messages, streamingMessageId],
  );

  const streamingVisible = useMemo(() => {
    if (!streamingMessage) return EMPTY_VISIBLE_MESSAGES;
    const sanitized = sanitizeContent(streamingMessage.content);
    if (!sanitized || sanitized.trim().length === 0) return EMPTY_VISIBLE_MESSAGES;
    return [
      {
        ...streamingMessage,
        content: sanitized,
      },
    ];
  }, [streamingMessage]);

  const visibleMessages = useMemo(
    () => [...visibleStable, ...streamingVisible],
    [visibleStable, streamingVisible],
  );

  return visibleMessages;
}
