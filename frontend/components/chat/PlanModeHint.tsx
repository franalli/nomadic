/**
 * PlanModeHint
 *
 * Pinned hint shown at top of chat in Plan mode.
 * "Type changes here. Updates appear in the plan."
 */

'use client';

import { ChevronDown, Info, X } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';

interface PlanModeHintProps {
  hasSetupHistory?: boolean;
  onViewSetup?: () => void;
}

export function PlanModeHint({ hasSetupHistory = false, onViewSetup }: PlanModeHintProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  return (
    <div
      className={cn(
        'sticky top-0 z-10',
        'flex items-center justify-between gap-2',
        'px-3 py-2 mb-3',
        'bg-zinc-900/90 backdrop-blur-sm rounded-lg',
        'border border-zinc-800/50',
        'text-xs text-zinc-400'
      )}
    >
      <div className="flex items-center gap-2">
        <Info className="h-3.5 w-3.5 text-zinc-500" />
        <span>Type changes here. Updates appear in the plan.</span>
      </div>

      <div className="flex items-center gap-2">
        {hasSetupHistory && onViewSetup && (
          <button
            type="button"
            onClick={onViewSetup}
            className="text-amber-500/80 hover:text-amber-400 flex items-center gap-1 transition-colors"
          >
            View setup
            <ChevronDown className="h-3 w-3" />
          </button>
        )}
        <button
          type="button"
          onClick={() => setDismissed(true)}
          className="text-zinc-600 hover:text-zinc-400 transition-colors"
          aria-label="Dismiss hint"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

export default PlanModeHint;
