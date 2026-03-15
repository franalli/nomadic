// frontend/components/chat/ChatMessageRenderer.tsx
'use client';

import { RotateCcw } from 'lucide-react';
import { memo } from 'react';

import { ChatMessageMarkdown, isRetryableError } from '@/components/chat/chatMessageMarkdown';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { ChatMessage } from '@/types/chat';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const MESSAGE_DELAY_CLASS_BY_MS: Record<number, string> = {
  0: '[animation-delay:0ms]',
  30: '[animation-delay:30ms]',
  60: '[animation-delay:60ms]',
  90: '[animation-delay:90ms]',
  120: '[animation-delay:120ms]',
  150: '[animation-delay:150ms]',
};

function getMessageDelayClass(idx: number): string {
  const delayMs = Math.min(idx * 30, 150);
  return MESSAGE_DELAY_CLASS_BY_MS[delayMs] ?? MESSAGE_DELAY_CLASS_BY_MS[150];
}

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

/** Extended message type that includes split-message metadata from ChatPanel */
export type VisibleMessage = ChatMessage & {
  _isPartOfSplit?: boolean;
  _isFirstPart?: boolean;
  _isLastPart?: boolean;
};

interface ChatMessageRendererProps {
  /** The message to render */
  message: VisibleMessage;
  /** Index in the visible messages array (used for stagger animation delay) */
  index: number;
  /** ID of the currently streaming message (null when not streaming) */
  streamingMessageId: string | null;
  /** Whether a request is in flight */
  isLoading: boolean;
  /** The last user message text, used for retry on transient errors */
  lastUserMessage: string | null;
  /** Callback to retry sending a message */
  onRetry: (message: string) => void;
  /** Landing mode — center messages instead of left/right alignment */
  isLanding?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

function ChatMessageRendererInner({
  message: m,
  index: idx,
  streamingMessageId,
  isLoading,
  lastUserMessage,
  onRetry,
  isLanding = false,
}: ChatMessageRendererProps) {
  // Check if this is part of a split message (for styling and retry button logic)
  const isSplitMessage = m._isPartOfSplit;
  const isFirstPart = m._isFirstPart;
  const isLastPart = m._isLastPart;
  // Extract original message ID for streaming check (handles split messages)
  const originalId = m.id.replace(/_p\d+$/, '');
  const isStreaming = streamingMessageId === originalId && !isSplitMessage;
  // Tighter spacing for consecutive parts of split messages
  const spacingClass = isSplitMessage && !isFirstPart ? '-mt-1.5' : '';

  const isUserMessage = m.role === 'user';
  const isInlineReceipt = m.displayMode === 'ack_line' || m.role === 'system';
  if (isInlineReceipt) return null;

  return (
    <div
      className={cn(
        isLanding ? 'text-center' : isUserMessage ? 'text-right' : 'text-left',
        'message-enter',
        spacingClass,
        getMessageDelayClass(idx),
      )}
    >
      {/* Message container */}
      <div className="inline-block relative max-w-[85%]">
        {isUserMessage ? (
          <div className="flex flex-col items-end">
            {/* The Commander (User Bubble) */}
            <div
              className={cn(
                // Shape: Speech bubble with sharp bottom-right corner
                'rounded-2xl rounded-br-md px-4 py-2.5 text-left transition-all',
                // Light Mode: Solid Black (The Commander)
                'bg-zinc-900 text-white border border-zinc-900',
                `${DS.shadow.bubble} hover:${DS.shadow.bubbleHover}`,
                'hover:bg-zinc-800 hover:border-zinc-800',
                // Dark Mode: Solid White (Maximum Contrast Signal)
                'dark:bg-white dark:text-zinc-950 dark:border-white',
                `dark:${DS.shadow.bubbleWhite}`,
                'dark:hover:bg-zinc-100'
              )}
            >
              {m.content}
            </div>
          </div>
        ) : (
          /* Assistant message */
          <div
            className={cn(
              // Shape: Speech bubble with sharp bottom-left corner
              'rounded-2xl rounded-bl-sm px-4 py-2.5 transition-all',
              // Light Mode: Glass effect
              'bg-white/80 backdrop-blur-sm',
              'border border-zinc-200',
              `${DS.shadow.bubble} hover:${DS.shadow.bubbleHover}`,
              // Dark Mode: Dark Glass (The System/Infrastructure)
              'dark:bg-white/5 dark:backdrop-blur-sm',
              'dark:border-white/10',
              'dark:shadow-none',
              // Text: High contrast
              'text-zinc-700 dark:text-zinc-300',
              isStreaming && 'typing-pulse'
            )}
          >
            <ChatMessageMarkdown content={m.content} />
            {/* Tier 11.12: Retry button for transient errors - only on last part of split messages */}
            {originalId.startsWith('a_err_') &&
              lastUserMessage &&
              isRetryableError(m.content) &&
              !isLoading &&
              (!isSplitMessage || isLastPart) && (
                <button
                  type="button"
                  onClick={() => onRetry(lastUserMessage)}
                  className="mt-2 flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 hover:text-emerald-500 dark:hover:text-emerald-300 transition-colors"
                >
                  <RotateCcw className="h-3 w-3" />
                  Retry
                </button>
              )}
          </div>
        )}
        {/* Delete button removed for demo - re-enable post-launch */}
      </div>
    </div>
  );
}

// Custom comparator: skip re-render when all meaningful props are identical.
// This prevents new spread-object `message` references from defeating memo.
function areChatMessagePropsEqual(
  prev: ChatMessageRendererProps,
  next: ChatMessageRendererProps,
): boolean {
  return (
    prev.message.id === next.message.id &&
    prev.message.content === next.message.content &&
    prev.message.role === next.message.role &&
    prev.message.displayMode === next.message.displayMode &&
    prev.message._isPartOfSplit === next.message._isPartOfSplit &&
    prev.message._isFirstPart === next.message._isFirstPart &&
    prev.message._isLastPart === next.message._isLastPart &&
    prev.streamingMessageId === next.streamingMessageId &&
    prev.isLoading === next.isLoading &&
    prev.lastUserMessage === next.lastUserMessage &&
    prev.isLanding === next.isLanding &&
    prev.index === next.index
  );
}

export const ChatMessageRenderer = memo(ChatMessageRendererInner, areChatMessagePropsEqual);
