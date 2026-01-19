'use client';

import { AlertCircle, Loader2 } from 'lucide-react';
import { memo } from 'react';

import { deriveEffectivePhase, formatMissing } from '@/lib/plan-status';
import { cn } from '@/lib/utils';
import type { PlanStatus } from '@/types/plan-status';

interface PlanHeaderStatusProps {
  status: PlanStatus;
  onRetry?: () => void;
  onFocusField?: (field: string) => void;
}

/**
 * PlanHeaderStatus - Single compact status pill for the Plan header.
 *
 * Renders one pill based on effectivePhase with strict precedence:
 * error > needs_input > updating > ready
 *
 * Copy:
 * - needs_input: "Awaiting origin, dates"
 * - updating: "Updating"
 * - error: "Update failed"
 * - ready: "Up to date" or "Pending update" (if dirty)
 */
export const PlanHeaderStatus = memo(function PlanHeaderStatus({
  status,
  onRetry,
  onFocusField,
}: PlanHeaderStatusProps) {
  const phase = deriveEffectivePhase(status);

  // Derive label based on phase
  const getLabel = (): string => {
    switch (phase) {
      case 'needs_input':
        return `Awaiting ${formatMissing(status.missing)}`;
      case 'updating':
        return 'Updating';
      case 'error':
        return 'Update failed';
      case 'ready':
        return status.dirty ? 'Pending update' : 'Up to date';
    }
  };

  // Click handler for actionable states
  const handleClick = () => {
    if (phase === 'error') {
      onRetry?.();
    } else if (phase === 'needs_input' && status.missing[0]) {
      onFocusField?.(status.missing[0]);
    }
  };

  const isClickable = phase === 'error' || phase === 'needs_input';

  // Phase-based text styles
  const phaseStyles: Record<PlanStatus['phase'], string> = {
    needs_input: 'text-muted-foreground',
    updating: 'text-primary/70',
    error: 'text-destructive/80',
    ready: status.dirty ? 'text-amber-600/80' : 'text-green-600/70',
  };

  return (
    <button
      type="button"
      onClick={isClickable ? handleClick : undefined}
      disabled={!isClickable}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[10px] font-medium transition-colors',
        'bg-muted/30 border border-border/20',
        phaseStyles[phase],
        isClickable && 'cursor-pointer hover:bg-muted/50 hover:border-border/40',
        !isClickable && 'cursor-default'
      )}
    >
      {/* Status indicator dot */}
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full',
          phase === 'updating' && 'bg-primary animate-pulse',
          phase === 'error' && 'bg-destructive',
          phase === 'ready' && !status.dirty && 'bg-green-500',
          phase === 'ready' && status.dirty && 'bg-amber-500',
          phase === 'needs_input' && 'bg-muted-foreground/50'
        )}
      />

      {/* Spinner for updating */}
      {phase === 'updating' && <Loader2 className="h-3 w-3 animate-spin" />}

      {/* Label */}
      <span>{getLabel()}</span>

      {/* Error icon */}
      {phase === 'error' && <AlertCircle className="h-3 w-3" />}
    </button>
  );
});
