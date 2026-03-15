'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * FreeDayCard
 *
 * Empty day state with specialist chip picker and "Generate Activities" CTA.
 * Shown when a day has no planned activities.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

import { BookOpen, PauseCircle, Search, ShieldAlert, Sparkles, Zap } from 'lucide-react';
import React, { useState } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

interface FreeDayCardProps {
  dayNumber: number;
  dayDate?: string | null;
  destination?: string | null;
  availableCategories?: Array<{ value: string; label: string; icon: string }>;
  onBrowse: () => void;
  onFillDay?: (dayNumber: number, dayDate: string | null, categories?: string[]) => void;
  isFilling?: boolean;
  isDisabled?: boolean;
  rejectionMessage?: string;
  /**
   * When true, all user-selected activity types are blocked by adjacent constraints.
   * Suppresses chips and auto-generate CTA; shows "Browse Activities" button only.
   * The user retains full agency — Browse opens the unfiltered activity picker.
   */
  isConstraintBuffer?: boolean;
  /** Optional DnD drop zone slot rendered between subtitle and chips */
  dropZoneSlot?: React.ReactNode;
}

export function FreeDayCard({
  dayNumber,
  dayDate,
  destination,
  availableCategories,
  onFillDay,
  isFilling,
  isDisabled = false,
  rejectionMessage,
  isConstraintBuffer = false,
  dropZoneSlot,
  onBrowse,
}: FreeDayCardProps) {
  // Mutually exclusive: one chip selected at a time (radio behavior)
  const [selectedCat, setSelectedCat] = useState<string | null>(null);

  const selectCategory = (cat: string) => {
    setSelectedCat(prev => prev === cat ? null : cat);
  };

  const handleFill = () => {
    const cats = selectedCat ? [selectedCat] : undefined;
    onFillDay?.(dayNumber, dayDate ?? null, cats);
  };

  // Constraint-buffer variant: all user activity types are blocked by adjacent constraints.
  // Show a buffer explanation and "Browse Activities" button (user agency preserved).
  // No chips, no auto-generate CTA.
  if (isConstraintBuffer) {
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

  return (
    <div className="p-6 bg-gradient-to-br from-zinc-50 to-zinc-100 dark:from-zinc-800/30 dark:to-zinc-900/30 rounded-xl border border-dashed border-zinc-300 dark:border-white/10">
      <div className="flex items-center justify-center gap-2 mb-4">
        <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <h4 className="text-base font-semibold text-zinc-900 dark:text-white">Free Day</h4>
      </div>
      <p className="text-sm text-zinc-600 dark:text-zinc-400 text-center mb-4">
        No activities planned{' '}
        <span className="dark:text-emerald-400">
          yet
        </span>
      </p>

      {/* DnD drop zone — injected by parent when DnD is active */}
      {dropZoneSlot}

      {/* Specialist chips — mutually exclusive (radio), none selected by default */}
      {availableCategories && availableCategories.length > 0 && (
        <div className="mb-4">
          <div className="flex flex-wrap justify-center gap-2">
            {availableCategories.map(cat => (
              <button
                key={cat.value}
                onClick={() => selectCategory(cat.value)}
                disabled={isDisabled}
                className={cn(
                  'px-3 py-1.5 rounded-full text-xs font-medium transition-all',
                  selectedCat === cat.value
                    ? 'bg-zinc-900 text-white border-2 border-transparent dark:bg-white dark:text-black dark:border-transparent'
                    : 'bg-white border-2 border-zinc-200 text-zinc-600 hover:border-zinc-900 hover:text-zinc-900 dark:bg-white/5 dark:border-2 dark:border-white/15 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white',
                  isDisabled && 'opacity-50 cursor-not-allowed pointer-events-none'
                )}
              >
                {cat.icon} {cat.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Browse more link — always visible below chips in free day mode */}
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
                  'bg-[linear-gradient(90deg,transparent,rgba(16,185,129,0.28),transparent)]',
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

      {/* Generate button — enabled when a chip is selected, or no chips available */}
      {onFillDay && destination && (
        <button
          onClick={handleFill}
          disabled={
            isDisabled
            || isFilling
            || (availableCategories && availableCategories.length > 0 && !selectedCat)
          }
          className={cn(
            DS.actions.primary,
            'bg-zinc-900 text-white hover:bg-zinc-800',
            'dark:bg-emerald-600 dark:hover:bg-emerald-500',
            'w-full px-4 py-2 text-sm font-medium flex items-center justify-center gap-1.5',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none'
          )}
        >
          {isFilling ? (
            'Generating...'
          ) : (
            <>
              <Zap className="w-4 h-4" />
              Generate Activities
            </>
          )}
        </button>
      )}

      {rejectionMessage && (
        <div className="mt-4 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/30 p-4">
          <ShieldAlert className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-700 dark:text-amber-300">
            {rejectionMessage}
          </p>
        </div>
      )}
    </div>
  );
}
