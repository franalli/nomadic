/**
 * FreeDayCard
 *
 * Empty day state with "Browse Activities" call-to-action.
 * Shown when a day has no planned activities.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

'use client';

import { Sparkles } from 'lucide-react';

export interface FreeDayCardProps {
  dayNumber: number;
  onBrowse: () => void;
}

export function FreeDayCard({ dayNumber, onBrowse }: FreeDayCardProps) {
  void dayNumber; // Reserved for future "Day X" display

  return (
    <div className="p-6 bg-gradient-to-br from-zinc-50 to-zinc-100 dark:from-zinc-800/30 dark:to-zinc-900/30 rounded-xl border border-dashed text-center">
      <div className="w-12 h-12 mx-auto rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center mb-3">
        <Sparkles className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
      </div>
      <h4 className="font-semibold text-foreground">Free Day</h4>
      <p className="text-sm text-muted-foreground mt-1 mb-4">
        No activities planned—perfect for spontaneous exploration!
      </p>
      <button
        onClick={onBrowse}
        className="px-4 py-2 text-sm font-medium bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors"
      >
        Browse Activities
      </button>
    </div>
  );
}
