// frontend/components/chat/ChatMessageRenderer.tsx
'use client';

import { RotateCcw } from 'lucide-react';
import React, { memo } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { preprocessSpecialistLinks } from '@/lib/specialistLinkParser';
import { getSpecialistColorRgb } from '@/lib/specialists';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { ChatMessage } from '@/types/chat';
import type { DayCard } from '@/types/plan-envelope';

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

// Tier 11.12: Check if an error message is retryable (transient network/server issues)
function isRetryableError(content: string): boolean {
  const retryablePatterns = [
    "couldn't connect",
    'check your internet',
    'took too long',
    'check your connection',
    'too quickly',
    'wait a moment',
    'went wrong on our end',
    'try again in a few',
  ];
  const lowerContent = content.toLowerCase();
  return retryablePatterns.some((pattern) => lowerContent.includes(pattern));
}

/** Extract plain text from React children (for fuzzy matching link text to block titles). */
function extractTextContent(node: React.ReactNode): string {
  if (typeof node === 'string') return node;
  if (Array.isArray(node)) return node.map(extractTextContent).join('');
  if (node && typeof node === 'object' && 'props' in node) {
    const el = node as { props?: { children?: React.ReactNode } };
    return extractTextContent(el.props?.children);
  }
  return '';
}

/** Find a block ID whose summary contains the entity name (case-insensitive substring). */
function findBlockByEntityName(entityName: string, dayCards?: DayCard[]): string | undefined {
  if (!dayCards || !entityName) return undefined;
  const needle = entityName.toLowerCase();
  for (const dc of dayCards) {
    for (const block of dc.blocks ?? []) {
      if (!block.id || !block.summary) continue;
      if (block.summary.toLowerCase().includes(needle) || needle.includes(block.summary.toLowerCase())) {
        return block.id;
      }
    }
  }
  return undefined;
}

// ─────────────────────────────────────────────────────────────────────────────
// Markdown components config — module-level to prevent recreation on each render
// Full GFM support with professional styling for chat bubbles
// ─────────────────────────────────────────────────────────────────────────────

const MARKDOWN_COMPONENTS = {
  // Paragraphs with proper spacing - mb-4 creates "Visual Islands" separation
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-4 last:mb-0 leading-relaxed">{children}</p>
  ),
  // Bold text with emphasis - zinc for key variables (dates, prices, locations)
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-zinc-900 dark:text-emerald-400">{children}</strong>
  ),
  // Italic text
  em: ({ children }: { children?: React.ReactNode }) => (
    <em className="italic">{children}</em>
  ),
  // Unordered lists with proper bullet styling
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="my-2 ml-1 list-none space-y-1.5 first:mt-0 last:mb-0">{children}</ul>
  ),
  // Ordered lists with proper number styling
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="my-2 ml-1 list-decimal space-y-1.5 pl-4 first:mt-0 last:mb-0">{children}</ol>
  ),
  // List items with custom bullet point styling (hidden when emoji acts as bullet)
  li: ({ children }: { children?: React.ReactNode }) => {
    // Extract text content to check if it starts with an emoji
    const getTextContent = (node: React.ReactNode): string => {
      if (typeof node === 'string') return node;
      if (Array.isArray(node)) return node.map(getTextContent).join('');
      if (node && typeof node === 'object' && 'props' in node) {
        const element = node as { props?: { children?: React.ReactNode } };
        return getTextContent(element.props?.children);
      }
      return '';
    };
    const text = getTextContent(children);
    const startsWithEmoji = /^[\p{Emoji_Presentation}\p{Extended_Pictographic}]/u.test(text);

    return (
      <li className={`relative pl-4 ${!startsWithEmoji ? "before:absolute before:left-0 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-zinc-900/60 dark:before:bg-zinc-400/60 before:content-['']" : ''}`}>
        {children}
      </li>
    );
  },
  // Inline code for technical terms
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-zinc-100/80 dark:bg-zinc-800/80 px-1 py-0.5 font-mono text-sm">{children}</code>
  ),
  // Links with proper styling - includes specialist deep link support
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    // Handle actcolor: protocol (colored activity name mentions → scroll to card)
    if (href?.startsWith('actcolor:')) {
      const specialistType = href.replace('actcolor:', '');
      const entityName = extractTextContent(children);
      const dayCards = useDocumentStore.getState().document?.day_cards;
      const matchingBlockId = findBlockByEntityName(entityName, dayCards);

      if (!matchingBlockId) {
        // No matching block — render as colored plain text, not clickable
        return (
          <span
            className="activity-mention font-medium"
            style={{ '--topic-color': getSpecialistColorRgb(specialistType) } as React.CSSProperties}
          >
            {children}
          </span>
        );
      }

      return (
        <span
          className="activity-mention font-medium cursor-pointer hover:underline"
          style={{ '--topic-color': getSpecialistColorRgb(specialistType) } as React.CSSProperties}
          data-specialist={specialistType}
          onClick={() => {
            const el = document.querySelector(`[data-block-id="${matchingBlockId}"]`);
            if (!el) return;
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.classList.remove('activity-scroll-highlight');
            // Force reflow so re-adding the class restarts the animation
            void (el as HTMLElement).offsetWidth;
            el.classList.add('activity-scroll-highlight');
          }}
        >
          {children}
        </span>
      );
    }
    // Handle specialist: protocol links (deep links to specialist cards)
    if (href?.startsWith('specialist:')) {
      const specialistType = href.replace('specialist:', '');
      return (
        <button
          type="button"
          onClick={() => {
            // Dispatch custom event for specialist navigation
            window.dispatchEvent(
              new CustomEvent('specialist-navigate', {
                detail: { specialistType },
              })
            );
          }}
          className="text-zinc-900 dark:text-emerald-400 font-semibold hover:underline cursor-pointer inline"
        >
          {children}
        </button>
      );
    }
    // Regular links — LLM may hallucinate URLs; render as emphasized plain text
    return (
      <span className="font-semibold text-zinc-900 dark:text-emerald-400">
        {children}
      </span>
    );
  },
  // Blockquotes for emphasis or quotes
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-emerald-500/40 pl-3 italic text-zinc-500 dark:text-zinc-400 first:mt-0 last:mb-0">
      {children}
    </blockquote>
  ),
  // Horizontal rules for section breaks
  hr: () => <hr className="my-3 border-zinc-200/50 dark:border-white/10" />,
  // Headers (rarely used in chat but supported)
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-2 text-lg font-bold text-zinc-900 dark:text-white first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-2 text-base font-semibold text-zinc-900 dark:text-white first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-1.5 text-sm font-semibold text-zinc-900 dark:text-white first:mt-0">{children}</h3>
  ),
};

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
                'shadow-[0_2px_8px_rgba(10,14,18,0.06)] hover:shadow-[0_4px_12px_rgba(10,14,18,0.08)]',
                'hover:bg-zinc-800 hover:border-zinc-800',
                // Dark Mode: Solid White (Maximum Contrast Signal)
                'dark:bg-white dark:text-zinc-950 dark:border-white',
                'dark:shadow-[0_0_10px_-6px_rgba(255,255,255,0.18)]',
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
              'shadow-[0_2px_8px_rgba(10,14,18,0.06)] hover:shadow-[0_4px_12px_rgba(10,14,18,0.08)]',
              // Dark Mode: Dark Glass (The System/Infrastructure)
              'dark:bg-white/5 dark:backdrop-blur-sm',
              'dark:border-white/10',
              'dark:shadow-none',
              // Text: High contrast
              'text-zinc-700 dark:text-zinc-300',
              isStreaming && 'typing-pulse'
            )}
          >
            <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
              {preprocessSpecialistLinks(m.content)}
            </Markdown>
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
