'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */

/**
 * MobileChatInput - Detached chat input for mobile swipe layout.
 *
 * Lives outside the MobileSwipeLayout scroll-snap container so it's
 * visible on both Chat and Plan pages. Relays messages via onSend
 * callback (wired to ChatPanelHandle.sendMessage in NomadicLanding).
 *
 * Design: matches ChatPanel's capsule shape (rounded-full).
 * Processing state: disabled + subtle pulse. No full Living Void.
 */

import { ArrowUp } from 'lucide-react';
import { memo, useCallback, useRef, useState } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

interface MobileChatInputProps {
  onSend: (message: string) => void;
  onStop?: () => void;
  isProcessing: boolean;
  hasDestination: boolean;
  hasPlan: boolean;
  className?: string;
}

function MobileChatInputInner({
  onSend,
  onStop,
  isProcessing,
  hasDestination,
  hasPlan,
  className,
}: MobileChatInputProps) {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const placeholder = isProcessing
    ? 'Updating...'
    : hasPlan
      ? 'Type to refine...'
      : !hasDestination
        ? 'Where to?'
        : 'Tell me more...';

  const handleSubmit = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault();
      const trimmed = input.trim();
      if (!trimmed || isProcessing) return;
      onSend(trimmed);
      setInput('');
      // Reset textarea height
      if (inputRef.current) {
        inputRef.current.style.height = 'auto';
      }
    },
    [input, isProcessing, onSend]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const canSend = input.trim().length > 0 && !isProcessing;

  return (
    <div
      className={cn(
        'shrink-0 px-3 pt-2 lg:hidden',
        'pb-[max(0.5rem,env(safe-area-inset-bottom))]',
        'border-t border-zinc-200 dark:border-white/5',
        'bg-white dark:bg-zinc-950',
        className
      )}
    >
      <div
        className={cn(
          'relative flex items-center w-full h-12 rounded-full transition-all duration-300',
          'bg-zinc-50 dark:bg-black/40',
          'shadow-[0_4px_16px_-4px_rgba(0,0,0,0.06)] dark:shadow-[0_4px_16px_-4px_rgba(0,0,0,0.3)]',
          'border border-zinc-200 dark:border-white/10',
          isProcessing && [
            'border-emerald-500/40 dark:border-emerald-500/30',
            `${DS.glowClass.mobileInputSm} dark:${DS.glowClass.mobileInputMd}`,
            'animate-pulse',
          ]
        )}
      >
        <form onSubmit={handleSubmit} className="flex-1 h-full flex items-center">
          <textarea
            ref={inputRef}
            disabled={isProcessing}
            aria-label="Chat message"
            className="w-full h-10 min-h-10 bg-transparent text-zinc-900 dark:text-white pl-5 pr-2 py-2.5 text-[16px] font-medium leading-5 resize-none overflow-hidden border-none outline-none focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
            placeholder={placeholder}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
        </form>

        <div className="pr-0.5 py-0.5 flex-shrink-0">
          {isProcessing && onStop ? (
            <button
              type="button"
              onClick={onStop}
              className={cn(
                'h-11 w-11 flex items-center justify-center rounded-full transition-all hover:scale-105 active:scale-95',
                'bg-zinc-200 dark:bg-white/10',
                'hover:bg-zinc-300 dark:hover:bg-white/20',
                'border border-zinc-300 dark:border-white/10'
              )}
              title="Stop"
              aria-label="Stop streaming"
            >
              <div className="w-2.5 h-2.5 bg-zinc-900 dark:bg-white rounded-sm" />
            </button>
          ) : (
            <button
              type="button"
              onClick={(e) => canSend && handleSubmit(e as unknown as React.FormEvent)}
              disabled={!canSend}
              className={cn(
                'flex items-center justify-center h-11 w-11 rounded-full transition-all duration-300',
                canSend
                  ? `bg-zinc-900 text-white shadow-lg shadow-zinc-900/10 hover:bg-zinc-800 dark:bg-emerald-600 dark:text-white dark:${DS.glowClass.lg} dark:hover:bg-emerald-500 hover:scale-105 active:scale-95`
                  : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600',
              )}
              title="Send message"
              aria-label="Send message"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export const MobileChatInput = memo(MobileChatInputInner);
