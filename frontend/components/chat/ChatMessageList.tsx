'use client';

/**
 * ChatMessageList — Scrollable message list renderer.
 *
 * Owns the scroll container div and all message rendering.
 * Scroll behaviour (refs, handlers) lives in ChatPanel and is
 * passed as props so ChatPanel retains control over scrollToBottom.
 */

import { isBootstrap } from '@/components/plan/planStateHelpers';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { PlanViewState } from '@/types/plan-envelope';

import { ChatMessageRenderer, type VisibleMessage } from './ChatMessageRenderer';
import { ChatSkeleton } from './ChatSkeleton';

interface ChatMessageListProps {
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  bottomSentinelRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  isLoadingHistory: boolean;
  isLoading: boolean;
  visibleMessages: VisibleMessage[];
  streamingMessageId: string | null;
  lastUserMessage: string | null;
  onRetry: (message: string) => void;
  isDesktop: boolean;
  planViewState?: PlanViewState;
  /** Landing mode — center messages in single-column layout */
  isLanding?: boolean;
  /** Content rendered at the top of the scroll area (hero banner + chips on desktop landing) */
  scrollHeaderContent?: React.ReactNode;
}

export function ChatMessageList({
  scrollContainerRef,
  bottomSentinelRef,
  onScroll,
  isLoadingHistory,
  isLoading,
  visibleMessages,
  streamingMessageId,
  lastUserMessage,
  onRetry,
  isDesktop,
  planViewState,
  isLanding = false,
  scrollHeaderContent,
}: ChatMessageListProps) {
  return (
    <div
      ref={scrollContainerRef}
      className={cn(
        'min-h-0 flex-1 overflow-y-auto text-sm no-scrollbar relative z-10 no-overflow-anchor',
        isLanding ? 'pt-[18vh]' : 'pt-2',
        !isDesktop && 'flex flex-col',
      )}
      role="log"
      aria-label="Chat messages"
      aria-busy={isLoadingHistory || isLoading}
      onScroll={onScroll}
    >
      {/* Inner wrapper: messages flow top-down; on mobile, mt-auto anchors to bottom */}
      <div className={cn('flex flex-col space-y-4', !isDesktop && visibleMessages.length > 0 && 'mt-auto')}>
        {/* Desktop landing: hero banner + chip row scroll inside the message list */}
        {scrollHeaderContent}

        {isLoadingHistory ? (
          <ChatSkeleton count={2} />
        ) : (
          <>
            {/* Mobile empty-state placeholder */}
            {!isDesktop && visibleMessages.length === 0 && isBootstrap(planViewState) && (
              <div className="flex flex-col items-center text-center px-6 mt-[42vh]">
                <span className="text-3xl mb-3" role="img" aria-label="Globe">🌍</span>
                <h2 className="text-lg font-semibold text-zinc-900 dark:text-white">
                  Where to next?
                </h2>
                <p className="text-sm text-zinc-400 dark:text-zinc-500 mt-1">
                  Try: &ldquo;Bali from Rome, Feb 11-14&rdquo;
                </p>
                <div className="mt-3 flex items-center gap-1.5">
                  <span className={`font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-emerald-600 dark:text-emerald-500 dark:${DS.glowClass.dropText}`}>
                    Awaiting Input
                  </span>
                  <div className={`w-1 h-1.5 bg-emerald-600 dark:bg-emerald-500 animate-terminal-blink rounded-sm dark:${DS.glowClass.cursor}`} />
                </div>
              </div>
            )}

            {visibleMessages.map((m, idx) => (
              <ChatMessageRenderer
                key={m.id}
                message={m}
                index={idx}
                streamingMessageId={streamingMessageId}
                isLoading={isLoading}
                lastUserMessage={lastUserMessage}
                onRetry={onRetry}
                isLanding={isLanding}
              />
            ))}
            {/* Invisible sentinel for smooth scroll-to-bottom */}
            <div ref={bottomSentinelRef} aria-hidden="true" className="h-px -mt-2" />
          </>
        )}
      </div>
    </div>
  );
}
