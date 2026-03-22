'use client';

import { BookOpen, PauseCircle, Search } from 'lucide-react';
import React from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// ConstraintBufferCard — shown when all user activity types are blocked
// ─────────────────────────────────────────────────────────────────────────────

interface ConstraintBufferCardProps {
  onBrowse: () => void;
  isDisabled: boolean;
  dropZoneSlot?: React.ReactNode;
}

export function ConstraintBufferCard({
  onBrowse,
  isDisabled,
  dropZoneSlot,
}: ConstraintBufferCardProps) {
  return (
    <div className="p-5 bg-zinc-50 dark:bg-zinc-800/20 rounded-xl border border-zinc-200 dark:border-white/10">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-9 h-9 rounded-full bg-zinc-100 dark:bg-zinc-700/40 flex items-center justify-center shrink-0">
          <PauseCircle className="w-5 h-5 text-zinc-500 dark:text-zinc-400" />
        </div>
        <div>
          <h4 className="text-sm font-semibold text-zinc-800 dark:text-zinc-200">Buffer Day</h4>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">Required between conflicting activities</p>
        </div>
      </div>
      {dropZoneSlot}
      <button
        onClick={onBrowse}
        disabled={isDisabled}
        className={cn(
          DS.actions.primary,
          'w-full px-4 py-2 text-sm font-medium flex items-center justify-center gap-2',
          isDisabled && 'opacity-50 cursor-not-allowed pointer-events-none'
        )}
      >
        <BookOpen className="w-4 h-4" />
        Browse Activities
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BrowseMoreButton — shimmer-animated "Browse more activities" link
// ─────────────────────────────────────────────────────────────────────────────

interface BrowseMoreButtonProps {
  onBrowse: () => void;
  isDisabled: boolean;
}

export function BrowseMoreButton({ onBrowse, isDisabled }: BrowseMoreButtonProps) {
  return (
    <div className="flex justify-center mb-2">
      <button
        type="button"
        onClick={onBrowse}
        disabled={isDisabled}
        className={cn(
          'text-sm font-medium inline-flex items-center gap-1.5',
          'text-zinc-600 dark:text-zinc-400',
          'hover:text-emerald-600 dark:hover:text-emerald-400',
          'transition-colors',
          isDisabled && 'opacity-50 cursor-not-allowed pointer-events-none'
        )}
      >
        <Search className="h-3.5 w-3.5 text-zinc-500 dark:text-zinc-400" />
        <span className="relative inline-flex">
          <span className={cn(isDisabled && 'text-zinc-500 dark:text-zinc-400', !isDisabled && 'text-zinc-600 dark:text-zinc-400')}>
            Browse more activities
          </span>
          {!isDisabled && (
            <span
              aria-hidden="true"
              className={cn(
                'pointer-events-none absolute inset-0 z-10',
                'text-transparent bg-clip-text',
                DS.gradient.emeraldSweep,
                'bg-[length:240%_100%]',
                'motion-safe:animate-[scan-shimmer_6.6s_ease-in-out_infinite]'
              )}
            >
              Browse more activities
            </span>
          )}
        </span>
      </button>
    </div>
  );
}
