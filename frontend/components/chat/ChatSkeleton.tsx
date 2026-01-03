/**
 * Skeleton loading state for chat history.
 *
 * Tier 9: Better perceived performance during initial load.
 * Shows animated placeholder messages that mimic actual chat structure.
 */

import { memo } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

type ChatSkeletonProps = {
  /** Number of message skeletons to show (default 3) */
  count?: number;
  className?: string;
};

/**
 * Single message skeleton - mimics assistant message structure.
 */
function MessageSkeleton({ isUser = false }: { isUser?: boolean }) {
  return (
    <div
      className={cn(
        'flex w-full gap-3 py-3',
        isUser && 'flex-row-reverse'
      )}
    >
      {/* Avatar skeleton */}
      <Skeleton
        className={cn(
          'h-8 w-8 shrink-0 rounded-full',
          isUser ? 'bg-primary/20' : 'bg-muted'
        )}
      />

      {/* Message content skeleton */}
      <div className={cn('flex flex-col gap-2', isUser ? 'items-end' : 'items-start')}>
        {/* Message bubble */}
        <div
          className={cn(
            'flex flex-col gap-2 rounded-2xl px-4 py-3',
            isUser
              ? 'bg-primary/10 rounded-br-sm'
              : 'bg-muted/50 rounded-bl-sm'
          )}
        >
          {/* Text lines */}
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-64" />
          {!isUser && <Skeleton className="h-4 w-40" />}
        </div>
      </div>
    </div>
  );
}

/**
 * Chat skeleton showing multiple placeholder messages.
 * Used during initial chat history load for better perceived performance.
 */
export const ChatSkeleton = memo(function ChatSkeleton({
  count = 3,
  className,
}: ChatSkeletonProps) {
  return (
    <div
      className={cn('flex flex-col gap-1 p-4', className)}
      role="status"
      aria-label="Loading chat history"
    >
      {/* Welcome message skeleton (always first) */}
      <MessageSkeleton isUser={false} />

      {/* Additional message pairs if count > 1 */}
      {count > 1 && (
        <>
          <MessageSkeleton isUser={true} />
          <MessageSkeleton isUser={false} />
        </>
      )}

      {/* Extra messages for larger counts */}
      {count > 2 && (
        <>
          <MessageSkeleton isUser={true} />
          <div className="flex w-full gap-3 py-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-full bg-muted" />
            <div className="flex flex-col gap-2">
              <div className="flex flex-col gap-2 rounded-2xl rounded-bl-sm bg-muted/50 px-4 py-3">
                <Skeleton className="h-4 w-56" />
                <Skeleton className="h-4 w-72" />
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-4 w-60" />
              </div>
            </div>
          </div>
        </>
      )}

      {/* Screen reader text */}
      <span className="sr-only">Loading chat history...</span>
    </div>
  );
});
