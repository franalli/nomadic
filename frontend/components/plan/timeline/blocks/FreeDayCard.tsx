/**
 * FreeDayCard
 *
 * Empty day state with "Browse Activities" call-to-action.
 * Shown when a day has no planned activities.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { Plus, Sparkles } from 'lucide-react';
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
}

export function FreeDayCard({
  dayNumber,
  dayDate,
  destination,
  availableCategories,
  onBrowse,
  onFillDay,
  isFilling,
}: FreeDayCardProps) {
  void dayNumber; // Reserved for future "Day X" display

  const [showPicker, setShowPicker] = useState(false);
  const [selectedCats, setSelectedCats] = useState<string[]>([]);

  const handleFill = () => {
    if (availableCategories && availableCategories.length > 1 && !showPicker) {
      setShowPicker(true);
      return;
    }
    onFillDay?.(dayNumber, dayDate ?? null, selectedCats.length > 0 ? selectedCats : undefined);
  };

  const toggleCategory = (cat: string) => {
    setSelectedCats(prev =>
      prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
    );
  };

  return (
    <div className="p-6 bg-gradient-to-br from-zinc-50 to-zinc-100 dark:from-zinc-800/30 dark:to-zinc-900/30 rounded-xl border border-dashed border-zinc-300 dark:border-white/10">
      <div className="flex items-center justify-center gap-2 mb-3">
        <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
          <Sparkles className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <h4 className="text-base font-semibold text-zinc-900 dark:text-white">Free Day</h4>
      </div>
      <p className="text-sm text-zinc-600 dark:text-zinc-400 text-center mb-4">
        No activities planned—perfect for spontaneous exploration!
      </p>

      {/* Category picker (inline, shown when showPicker is true) */}
      {showPicker && availableCategories && (
        <div className="mb-4">
          <div className="flex gap-2 overflow-x-auto no-scrollbar py-1">
            {availableCategories.map(cat => (
              <button
                key={cat.value}
                onClick={() => toggleCategory(cat.value)}
                className={cn(
                  'shrink-0 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all',
                  selectedCats.includes(cat.value)
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

      {/* Action buttons */}
      <div className="flex gap-2">
        <button
          onClick={onBrowse}
          className={cn(
            'flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors',
            'bg-white dark:bg-white/5 border border-zinc-200 dark:border-white/15',
            'text-zinc-900 dark:text-white hover:bg-zinc-50 dark:hover:bg-white/10'
          )}
        >
          Browse Activities
        </button>
        {onFillDay && destination && (
          <button
            onClick={handleFill}
            disabled={isFilling}
            className={cn(
              'flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-all',
              'bg-zinc-900 text-white hover:bg-zinc-800',
              'dark:bg-emerald-600 dark:hover:bg-emerald-500',
              'disabled:opacity-50 disabled:cursor-not-allowed'
            )}
          >
            {showPicker ? (
              'Generate Activities'
            ) : isFilling ? (
              'Filling...'
            ) : (
              <>
                <Plus className="w-4 h-4 inline mr-1" />
                Fill Day
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
