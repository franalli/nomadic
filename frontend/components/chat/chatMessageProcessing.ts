// frontend/components/chat/chatMessageProcessing.ts
//
// Pure (non-React) message processing utilities extracted from ChatPanel.
// These are deterministic transforms with no side effects, making them
// independently testable without rendering.

import type { ChatMessage } from '@/types/chat';

import type { VisibleMessage } from './ChatMessageRenderer';

// ─────────────────────────────────────────────────────────────────────────────
// getSendBurstGuardReason
// ─────────────────────────────────────────────────────────────────────────────

const MESSAGE_BURST_COOLDOWN_MS = 1000;
const GENERATE_BURST_COOLDOWN_MS = 3000;

type SendBurstGuardParams = {
  isGenerateTrigger: boolean;
  isLoading: boolean;
  now: number;
  lastMessageSentAt: number;
  lastGenerateClickedAt: number;
};

export function getSendBurstGuardReason(params: SendBurstGuardParams): string | null {
  const {
    isGenerateTrigger,
    isLoading,
    now,
    lastMessageSentAt,
    lastGenerateClickedAt,
  } = params;
  if (isGenerateTrigger) {
    if (isLoading) return 'Plan generation already in progress';
    if (now - lastGenerateClickedAt < GENERATE_BURST_COOLDOWN_MS) {
      return 'Please wait a moment before generating again';
    }
    return null;
  }
  if (isLoading) return 'loading';
  if (now - lastMessageSentAt < MESSAGE_BURST_COOLDOWN_MS) {
    return "You're sending too quickly";
  }
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// sanitizeContent
// ─────────────────────────────────────────────────────────────────────────────

/** Fix escaped characters from backend and strip "check the right panel" noise. */
export const sanitizeContent = (content: string): string => {
  return content
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\\*/g, '*')
    .replace(/\s*(?:[-–—]\s*)?[Cc]heck\s+(?:the\s+)?right\s+panel[^.!?\n]*[.!]?/g, '')
    .trim();
};

// ─────────────────────────────────────────────────────────────────────────────
// EMPTY_VISIBLE_MESSAGES
// ─────────────────────────────────────────────────────────────────────────────

/** Stable empty array to avoid new [] identity on every render when not streaming. */
export const EMPTY_VISIBLE_MESSAGES: VisibleMessage[] = [];

// ─────────────────────────────────────────────────────────────────────────────
// splitMessageIfNeeded
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Split a single assistant message into multiple VisibleMessage bubbles
 * when the content contains multiple paragraphs or is long enough to
 * benefit from visual chunking.
 */
export function splitMessageIfNeeded(m: VisibleMessage): VisibleMessage[] {
  if (m.role !== 'assistant') return [m];
  const paragraphs = m.content.split(/\n\n+/).filter((p) => p.trim().length > 0);
  if (paragraphs.length > 1) {
    return paragraphs.map((paragraph, idx) => ({
      ...m,
      id: `${m.id}_p${idx}`,
      content: paragraph.trim(),
      _isPartOfSplit: true,
      _isFirstPart: idx === 0,
      _isLastPart: idx === paragraphs.length - 1,
    }));
  }
  const words = m.content.split(/\s+/).filter(Boolean).length;
  const sentences = m.content.split(/(?<=[.!?])\s+(?=[A-Z])/).filter((s) => s.trim());
  if (sentences.length >= 3 && words > 40) {
    const parts = [sentences[0].trim(), sentences.slice(1).join(' ').trim()];
    return parts.map((part, idx) => ({
      ...m,
      id: `${m.id}_p${idx}`,
      content: part,
      _isPartOfSplit: true,
      _isFirstPart: idx === 0,
      _isLastPart: idx === parts.length - 1,
    }));
  }
  return [m];
}

// ─────────────────────────────────────────────────────────────────────────────
// buildVisibleMessages
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Filter, sanitize, and split stable (non-streaming) messages into the
 * VisibleMessage[] array consumed by ChatMessageList.
 */
export function buildVisibleMessages(
  stableMessages: ChatMessage[],
  isGenerating: boolean,
  hasBranches: boolean,
): VisibleMessage[] {
  const visible: VisibleMessage[] = [];

  for (const message of stableMessages) {
    if (message.role === 'system' || message.displayMode === 'ack_line') continue;
    if (!message.content || message.content.trim().length === 0) continue;
    if (isGenerating && message.id === 'm0') continue;

    const canonicalContent =
      hasBranches && message.id === 'm0' ? 'Edit constraints.' : message.content;
    const sanitized = sanitizeContent(canonicalContent);
    if (!sanitized || sanitized.trim().length === 0) continue;

    const normalized: VisibleMessage = { ...message, content: sanitized };
    const split = splitMessageIfNeeded(normalized);
    visible.push(...split);
  }

  return visible;
}
