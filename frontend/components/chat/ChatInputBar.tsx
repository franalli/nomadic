/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { ArrowUp } from 'lucide-react';

import { isBootstrap } from '@/components/plan/planStateHelpers';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { PlanViewState } from '@/types/plan-envelope';

interface ChatInputBarProps {
  input: string;
  onInputChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  isLoading: boolean;
  isInputDisabledByPlanState: boolean;
  hasReceivedFirstToken: boolean;
  nodeStatus: { node: string } | null;
  readyToGenerate?: boolean;
  isGenerating?: boolean;
  hasBranches?: boolean;
  hasDestination?: boolean;
  planViewState?: PlanViewState;
  onStopStreaming: () => void;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}

export function ChatInputBar({
  input,
  onInputChange,
  onSubmit,
  isLoading,
  isInputDisabledByPlanState,
  hasReceivedFirstToken,
  nodeStatus,
  readyToGenerate,
  isGenerating,
  hasBranches,
  hasDestination,
  planViewState,
  onStopStreaming,
  inputRef,
}: ChatInputBarProps) {
  return (
    <>
      {/* Action Bar: Unified Capsule Design with "Living Void" Effect */}
      {/* Input and button merged into one continuous capsule (like Perplexity/ChatGPT) */}
      {/* During AI processing: the input BECOMES the status indicator (emerald glow + pulse) */}
      <div
        className={cn(
          'relative flex items-center w-full min-h-14 rounded-[28px] transition-all duration-300',
          'bg-zinc-50 dark:bg-black/40',
          // Priority 1: "Living Void" - AI Processing state
          isLoading && nodeStatus?.node
            ? [
                'border border-emerald-500/50 dark:border-emerald-500/40',
                `${DS.glowClass.sm} dark:${DS.glowClass.md}`,
                'animate-pulse',
              ]
            // Priority 2: Ready to Generate highlight
            : readyToGenerate && !input.trim() && isBootstrap(planViewState) && !isGenerating && !hasBranches
              ? `border border-emerald-500/50 ring-1 ring-emerald-500/30 dark:${DS.glowClass.sm}`
              // Default state
              : [
                  'shadow-[0_8px_30px_-8px_rgba(0,0,0,0.08)] dark:shadow-[0_8px_30px_-8px_rgba(0,0,0,0.3)]',
                  'border border-zinc-200 dark:border-white/10',
                ]
        )}
      >
        {/* Input Field - takes remaining space */}
        {/* Note: Status text removed - Logic Terminal in chat list is the single source of truth (DS Section 19.C) */}
        <form onSubmit={onSubmit} className="flex-1 h-full">
          <textarea
            ref={inputRef}
            disabled={isInputDisabledByPlanState}
            className="w-full bg-transparent text-zinc-900 dark:text-white pl-6 pr-2 py-4 text-sm font-medium leading-5 resize-none overflow-hidden border-none outline-none focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
            placeholder={
              isInputDisabledByPlanState
                ? 'Updating...'
                : readyToGenerate
                  ? 'Type to refine...'
                  : !hasDestination
                    ? 'Where to?'
                    : 'Tell me more...'
            }
            value={input}
            onChange={(e) => {
              onInputChange(e.target.value);
              // Auto-grow textarea to fit content (max 5 rows)
              const el = e.target;
              el.style.height = 'auto';
              el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
            }}
            onKeyDown={(e) => {
              // Submit on Enter without Shift
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSubmit(e);
              }
            }}
            rows={1}
          />
        </form>

        {/* Button - inside the capsule */}
        <div className="pr-1.5 py-1.5 flex-shrink-0">
          {isLoading && hasReceivedFirstToken ? (
            // Stop streaming button - minimal monochrome (not red - that's for errors)
            <button
              type="button"
              onClick={onStopStreaming}
              className={cn(
                'h-11 w-11 flex items-center justify-center rounded-[22px] transition-all hover:scale-105 active:scale-95',
                'bg-zinc-200 dark:bg-white/10',
                'hover:bg-zinc-300 dark:hover:bg-white/20',
                'border border-zinc-300 dark:border-white/10'
              )}
              title="Stop"
            >
              {/* Minimal square icon - matches theme */}
              <div className="w-3 h-3 bg-zinc-900 dark:bg-white rounded-[2px]" />
            </button>
          ) : (
            // SEND STATE: Arrow button inside capsule
            <button
              type="button"
              onClick={(e) => input.trim() && onSubmit(e as unknown as React.FormEvent)}
              disabled={isLoading || !input.trim()}
              className={cn(
                'flex items-center justify-center h-11 w-11 rounded-[22px] transition-all duration-300',
                input.trim() && !isLoading
                  ? `bg-zinc-900 text-white shadow-lg shadow-zinc-900/10 hover:bg-zinc-800 dark:bg-emerald-600 dark:text-white dark:${DS.glowClass.lg} dark:hover:bg-emerald-500 hover:scale-105 active:scale-95`
                  : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600',
              )}
              title="Send message (Enter)"
            >
              <ArrowUp className="h-5 w-5" />
            </button>
          )}
        </div>
      </div>
    </>
  );
}
