/**
 * PreferenceAttributionBadge
 *
 * Shows why a tile was selected in the itinerary:
 * - user_preferred: "You preferred this hotel"
 * - ai_selected: (no badge - default behavior)
 * - ai_override: "AI selected" + switch option
 */

'use client';

import { Heart, RefreshCw } from 'lucide-react';

import { cn } from '@/lib/utils';

export type PreferenceStatus = 'user_preferred' | 'ai_selected' | 'ai_override';

interface PreferenceAttributionBadgeProps {
  status?: PreferenceStatus;
  alternativeTileId?: string;
  onSwitchToAlternative?: (tileId: string) => void;
  className?: string;
}

export function PreferenceAttributionBadge({
  status,
  alternativeTileId,
  onSwitchToAlternative,
  className,
}: PreferenceAttributionBadgeProps) {
  // Don't show badge for ai_selected (default behavior)
  if (!status || status === 'ai_selected') {
    return null;
  }

  if (status === 'user_preferred') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1',
          'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 text-xs font-medium',
          className
        )}
      >
        <Heart className="h-3 w-3 fill-emerald-600 dark:fill-emerald-400" />
        You preferred this
      </div>
    );
  }

  if (status === 'ai_override' && alternativeTileId) {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 rounded-full px-2.5 py-1',
          'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400 text-xs font-medium',
          className
        )}
      >
        <span>AI selected</span>
        {onSwitchToAlternative && (
          <button
            type="button"
            onClick={() => onSwitchToAlternative(alternativeTileId)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-zinc-200 hover:bg-zinc-300 text-zinc-600 dark:bg-zinc-700/50 dark:hover:bg-zinc-700 dark:text-zinc-300 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            Switch
          </button>
        )}
      </div>
    );
  }

  return null;
}

export default PreferenceAttributionBadge;
