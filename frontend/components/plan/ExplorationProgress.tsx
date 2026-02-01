/**
 * ExplorationProgress
 *
 * Shows question count during exploration phase and prompts user to start planning
 * after 3+ questions have been asked.
 *
 * @see docs/ux_unified_architecture.md Section I.A
 */

'use client';

import { ArrowRight, MessageSquare } from 'lucide-react';

import { cn } from '@/lib/utils';

interface ExplorationProgressProps {
  questionCount: number;
  destination?: string;
  onPlanNow?: () => void;
  className?: string;
}

export function ExplorationProgress({
  questionCount,
  destination,
  onPlanNow,
  className,
}: ExplorationProgressProps) {
  if (questionCount === 0) return null;

  const showPlanPrompt = questionCount >= 3;

  return (
    <div
      className={cn(
        'bg-gradient-to-r from-emerald-50 to-blue-50 dark:from-emerald-950/20 dark:to-blue-950/20',
        'border border-emerald-200 dark:border-emerald-800/40',
        'rounded-lg p-4',
        className
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="bg-white dark:bg-zinc-800 rounded-full p-2 shadow-sm">
            <MessageSquare className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                {questionCount} question{questionCount === 1 ? '' : 's'} asked
              </span>
              {showPlanPrompt && (
                <span className="text-xs bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400 px-2 py-0.5 rounded-full font-medium">
                  Ready to plan!
                </span>
              )}
            </div>
            {showPlanPrompt && destination && (
              <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-0.5">
                I have enough context to plan your {destination} trip
              </p>
            )}
          </div>
        </div>

        {showPlanPrompt && onPlanNow && (
          <button
            onClick={onPlanNow}
            className={cn(
              'flex items-center gap-2 shrink-0',
              'bg-emerald-600 text-white',
              'px-4 py-2 rounded-md',
              'hover:bg-emerald-700 transition-colors',
              'text-sm font-medium'
            )}
          >
            Plan now
            <ArrowRight className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}
