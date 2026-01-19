'use client';

import { AlertTriangle, Undo2 } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { AppliedUpdateKey, Conflict, UndoSnapshot } from '@/types/plan-envelope';

interface ReceiptStripProps {
  appliedUpdates: AppliedUpdateKey[];
  conflicts: Conflict[];
  undoSnapshot: UndoSnapshot | null;
  onUndo?: () => void;
  className?: string;
}

/**
 * Get human-readable label for an applied update key.
 */
function getUpdateLabel(key: AppliedUpdateKey): string {
  const labels: Record<AppliedUpdateKey, string> = {
    origin: 'Origin',
    destination: 'Destination',
    dates: 'Dates',
    travelers: 'Travelers',
    budget: 'Budget',
  };
  return labels[key];
}

/**
 * Get human-readable message for a conflict code.
 */
function getConflictMessage(conflict: Conflict): string {
  const messages: Record<Conflict['code'], string> = {
    date_range_invalid: 'Invalid date range',
    date_past: 'Date is in the past',
    budget_exceeded: 'Budget exceeded',
    traveler_mismatch: 'Traveler count mismatch',
    destination_unreachable: 'Destination unreachable',
    duration_mismatch: 'Duration mismatch',
  };
  return messages[conflict.code];
}

/**
 * ReceiptStrip - Shows applied updates and conflicts with optional undo.
 *
 * Displays:
 * - Applied updates as inline badges
 * - Conflicts with warning icon
 * - Undo button (if snapshot available)
 */
export const ReceiptStrip = memo(function ReceiptStrip({
  appliedUpdates,
  conflicts,
  undoSnapshot,
  onUndo,
  className,
}: ReceiptStripProps) {
  if (appliedUpdates.length === 0 && conflicts.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-md border border-border/20 bg-muted/20 px-3 py-2 text-xs',
        className
      )}
    >
      {/* Applied updates */}
      {appliedUpdates.length > 0 && (
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground/70">Updated:</span>
          {appliedUpdates.map((key) => (
            <span
              key={key}
              className="inline-flex items-center rounded bg-green-500/10 px-1.5 py-0.5 text-green-600"
            >
              {getUpdateLabel(key)}
            </span>
          ))}
        </div>
      )}

      {/* Conflicts */}
      {conflicts.length > 0 && (
        <div className="flex items-center gap-1.5">
          {conflicts.map((conflict, idx) => (
            <span
              key={`${conflict.scope}-${idx}`}
              className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-600"
            >
              <AlertTriangle className="h-3 w-3" />
              {getConflictMessage(conflict)}
            </span>
          ))}
        </div>
      )}

      {/* Undo button */}
      {undoSnapshot && onUndo && (
        <button
          type="button"
          onClick={onUndo}
          className="ml-auto inline-flex items-center gap-1 rounded px-2 py-0.5 text-muted-foreground hover:bg-muted/50 hover:text-foreground transition-colors"
        >
          <Undo2 className="h-3 w-3" />
          Undo
        </button>
      )}
    </div>
  );
});
