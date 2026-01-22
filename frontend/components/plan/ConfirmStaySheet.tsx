/**
 * ConfirmStaySheet
 *
 * One-time confirmation when user tries to create itinerary without saving any stays.
 * Options:
 * - "Use recommended" - Auto-pick recommended stay
 * - "Choose a stay" - Go back to shortlist stays
 */

'use client';

import { Hotel, Star } from 'lucide-react';
import { memo } from 'react';

import { BaseSheet } from '@/components/planner/sheets/BaseSheet';
import { cn } from '@/lib/utils';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ConfirmStaySheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called when user chooses to use recommended stay */
  onUseRecommended: () => void;
  /** Called when user wants to choose a stay manually */
  onChooseStay: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export const ConfirmStaySheet = memo(function ConfirmStaySheet({
  open,
  onOpenChange,
  onUseRecommended,
  onChooseStay,
}: ConfirmStaySheetProps) {
  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="No stay selected"
      hint="You haven't saved a stay to your shortlist yet"
    >
      <div className="space-y-4 py-2">
        {/* Explanation */}
        <p className="text-sm text-zinc-400">
          Your itinerary needs a stay. What would you like to do?
        </p>

        {/* Options */}
        <div className="space-y-3">
          {/* Use recommended */}
          <button
            type="button"
            onClick={onUseRecommended}
            className={cn(
              'w-full flex items-start gap-3 p-4 rounded-lg',
              'border border-zinc-700 bg-zinc-800/50',
              'text-left transition-colors',
              'hover:border-amber-500/50 hover:bg-amber-500/5'
            )}
          >
            <div className="flex-shrink-0 mt-0.5">
              <Star className="h-5 w-5 text-amber-400" />
            </div>
            <div>
              <div className="font-medium text-zinc-200">Use recommended</div>
              <p className="mt-0.5 text-sm text-zinc-500">
                We'll pick the best-rated stay that fits your budget
              </p>
            </div>
          </button>

          {/* Choose a stay */}
          <button
            type="button"
            onClick={onChooseStay}
            className={cn(
              'w-full flex items-start gap-3 p-4 rounded-lg',
              'border border-zinc-700 bg-zinc-800/50',
              'text-left transition-colors',
              'hover:border-zinc-600 hover:bg-zinc-800'
            )}
          >
            <div className="flex-shrink-0 mt-0.5">
              <Hotel className="h-5 w-5 text-zinc-400" />
            </div>
            <div>
              <div className="font-medium text-zinc-200">Choose a stay</div>
              <p className="mt-0.5 text-sm text-zinc-500">
                Go back and save a stay to your shortlist first
              </p>
            </div>
          </button>
        </div>

        {/* Cancel link */}
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="w-full text-center text-sm text-zinc-500 hover:text-zinc-400 transition-colors"
        >
          Cancel
        </button>
      </div>
    </BaseSheet>
  );
});

export default ConfirmStaySheet;
