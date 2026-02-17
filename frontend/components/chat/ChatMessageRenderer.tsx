// frontend/components/chat/ChatMessageRenderer.tsx
'use client';

import { RotateCcw } from 'lucide-react';
import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { preprocessSpecialistLinks } from '@/lib/specialistLinkParser';
import { cn } from '@/lib/utils';
import type { ChatMessage } from '@/types/chat';

import { SystemAckLine } from './SystemAckLine';
import { SystemReceipt } from './SystemReceipt';

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

export function getMessageDelayClass(idx: number): string {
  const delayMs = Math.min(idx * 30, 150);
  return MESSAGE_DELAY_CLASS_BY_MS[delayMs] ?? MESSAGE_DELAY_CLASS_BY_MS[150];
}

// Tier 11.12: Check if an error message is retryable (transient network/server issues)
export function isRetryableError(content: string): boolean {
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
      <li className={`relative pl-4 ${!startsWithEmoji ? "before:absolute before:left-0 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-primary/60 before:content-['']" : ''}`}>
        {children}
      </li>
    );
  },
  // Inline code for technical terms
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-muted/50 px-1 py-0.5 font-mono text-sm">{children}</code>
  ),
  // Links with proper styling - includes specialist deep link support
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
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
    // Regular external links
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline decoration-primary/50 underline-offset-2 hover:decoration-primary transition-colors"
      >
        {children}
      </a>
    );
  },
  // Blockquotes for emphasis or quotes
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-primary/40 pl-3 italic text-muted-foreground first:mt-0 last:mb-0">
      {children}
    </blockquote>
  ),
  // Horizontal rules for section breaks
  hr: () => <hr className="my-3 border-border/50" />,
  // Headers (rarely used in chat but supported)
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-2 text-lg font-bold first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-2 text-base font-semibold first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-1.5 text-sm font-semibold first:mt-0">{children}</h3>
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
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function ChatMessageRenderer({
  message: m,
  index: idx,
  streamingMessageId,
  isLoading,
  lastUserMessage,
  onRetry,
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

  // Check if this user message has ack updates (for SystemReceipt display)
  const hasAckUpdates = isUserMessage && m.ackUpdates && m.ackUpdates.length > 0;

  // Render system ack line for system messages or ack_line displayMode
  if (m.role === 'system' || m.displayMode === 'ack_line') {
    return (
      <div
        className={cn('message-enter', getMessageDelayClass(idx))}
      >
        <SystemAckLine
          status={m.ackStatus || 'applied'}
          updates={m.ackUpdates}
          isPending={m.ackStatus === 'pending'}
        />
      </div>
    );
  }

  return (
    <div
      className={cn(
        isUserMessage ? 'text-right' : 'text-left',
        'message-enter',
        spacingClass,
        getMessageDelayClass(idx),
      )}
    >
      {/* Message container */}
      <div className="inline-block relative max-w-[85%]">
        {/* "Command & Receipt" pattern: User message + SystemReceipt below */}
        {isUserMessage ? (
          <div className="flex flex-col items-end">
            {/* The Commander (User Bubble) */}
            <div
              className={cn(
                // Shape: Speech bubble with sharp bottom-right corner
                'rounded-2xl rounded-br-md px-4 py-2.5 text-left transition-all',
                // Light Mode: Solid Black (The Commander)
                'bg-zinc-900 text-white border border-zinc-900',
                'shadow-md hover:shadow-lg hover:-translate-y-0.5',
                'hover:bg-zinc-800 hover:border-zinc-800',
                // Dark Mode: Solid White (Maximum Contrast Signal)
                'dark:bg-white dark:text-zinc-950 dark:border-white',
                'dark:shadow-[0_0_20px_-5px_rgba(255,255,255,0.3)]',
                'dark:hover:bg-zinc-100'
              )}
            >
              {m.content}
            </div>
            {/* The System Receipt - DS Section 19 */}
            {hasAckUpdates && (
              <SystemReceipt
                ackStatus={m.ackStatus || 'applied'}
                ackUpdates={m.ackUpdates || []}
              />
            )}
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
              'shadow-sm',
              'hover:shadow-md hover:-translate-y-0.5',
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
                  className="mt-2 flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 transition-colors"
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
