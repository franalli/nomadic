'use client';

import { ChevronDown, ChevronUp, RefreshCw, Sparkles } from 'lucide-react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// Re-export so existing consumers keep working
export { SuggestionCardCompact } from './suggestionCardSectionsParts';

export function SuggestionReasoning({ reasoning, isExpanded, onToggle }: { reasoning: string; isExpanded: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 dark:border-white/5 dark:bg-white/[0.03]">
      <button onClick={onToggle} aria-label="Why this suggestion? Toggle details" className="flex w-full items-center justify-between p-3 text-left">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-emerald-500 dark:text-emerald-400" />
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Why this suggestion?</span>
        </div>
        {isExpanded ? <ChevronUp className="h-4 w-4 text-zinc-400" /> : <ChevronDown className="h-4 w-4 text-zinc-400" />}
      </button>
      {isExpanded && (
        <div className="px-3 pb-3">
          <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{reasoning}</p>
        </div>
      )}
    </div>
  );
}

export function SuggestionActionRow({
  tile,
  isSaved,
  onSave,
  onViewAlternatives,
  onDetailsClick,
}: {
  tile: Tile;
  isSaved: boolean;
  onSave?: (tile: Tile) => void;
  onViewAlternatives?: () => void;
  onDetailsClick?: (tile: Tile) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={onViewAlternatives}
        className="flex items-center gap-1.5 rounded-lg bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:bg-zinc-700/50 dark:text-zinc-300 dark:hover:bg-zinc-700"
      >
        <RefreshCw className="h-4 w-4" />
        Change
      </button>
      <button
        onClick={() => onDetailsClick?.(tile)}
        className="flex-1 rounded-lg bg-zinc-100 px-3 py-2 text-center text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:bg-zinc-700/50 dark:text-zinc-300 dark:hover:bg-zinc-700"
      >
        View Details
      </button>
      <button
        onClick={() => onSave?.(tile)}
        className={cn(
          'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
          isSaved
            ? 'border border-emerald-500/30 bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
            : DS.actions.primary
        )}
      >
        {isSaved ? 'Saved' : 'Save to Trip'}
      </button>
    </div>
  );
}
