/**
 * FreeDayCard
 *
 * Empty day state with specialist chip picker and "Generate Activities" CTA.
 * Shown when a day has no planned activities.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { ShieldAlert, Sparkles } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';

export interface FreeDayCardProps {
  dayNumber: number;
  dayDate?: string | null;
  destination?: string | null;
  availableCategories?: Array<{ value: string; label: string; icon: string }>;
  onBrowse: () => void;
  onFillDay?: (dayNumber: number, dayDate: string | null, categories?: string[]) => void;
  isFilling?: boolean;
  rejectionMessage?: string;
}

export function FreeDayCard({
  dayNumber,
  dayDate,
  destination,
  availableCategories,
  onFillDay,
  isFilling,
  rejectionMessage,
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

  return (
    <div className="p-6 bg-gradient-to-br from-zinc-50 to-zinc-100 dark:from-zinc-800/30 dark:to-zinc-900/30 rounded-xl border border-dashed border-zinc-300 dark:border-white/10">
      <div className="flex items-center justify-center gap-2 mb-4">
        <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <h4 className="text-base font-semibold text-zinc-900 dark:text-white">Free Day</h4>
      </div>
      <p className="text-sm text-zinc-600 dark:text-zinc-400 text-center mb-4">
        No activities planned
      </p>

      {/* Specialist chips — mutually exclusive (radio), none selected by default */}
      {availableCategories && availableCategories.length > 0 && (
        <div className="mb-4">
          <div className="flex flex-wrap justify-center gap-2">
            {availableCategories.map(cat => (
              <button
                key={cat.value}
                onClick={() => selectCategory(cat.value)}
                className={cn(
                  'px-3 py-1.5 rounded-full text-xs font-medium transition-all',
                  selectedCat === cat.value
                    ? 'bg-zinc-900 text-white dark:bg-white dark:text-black'
                    : 'bg-white border border-zinc-200 text-zinc-600 dark:bg-white/5 dark:border-white/15 dark:text-zinc-400'
                )}
              >
                {cat.icon} {cat.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Generate button — enabled when a chip is selected, or no chips available */}
      {onFillDay && destination && (
        <button
          onClick={handleFill}
          disabled={isFilling || (availableCategories && availableCategories.length > 0 && !selectedCat)}
          className={cn(
            'w-full px-4 py-2 text-sm font-medium rounded-lg transition-all',
            'bg-zinc-900 text-white hover:bg-zinc-800',
            'dark:bg-emerald-600 dark:hover:bg-emerald-500',
            'disabled:opacity-50 disabled:cursor-not-allowed'
          )}
        >
          {isFilling ? 'Generating...' : 'Generate Activities'}
        </button>
      )}

      {rejectionMessage && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/30 p-3">
          <ShieldAlert className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-700 dark:text-amber-300">
            {rejectionMessage}
          </p>
        </div>
      )}
    </div>
  );
}
