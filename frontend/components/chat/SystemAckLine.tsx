/**
 * SystemAckLine
 *
 * Compact status line for Plan mode acknowledgments.
 * Shows: "Updating plan..." → "Applied: added Diving · duration 1 week"
 */

'use client';

import { AlertCircle, Check, Loader2, Minus } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { AckStatus, AckUpdate } from '@/types/chat';

interface SystemAckLineProps {
  status: AckStatus;
  updates?: AckUpdate[];
  isPending?: boolean;
}

function formatUpdates(updates: AckUpdate[]): string {
  if (updates.length === 0) return 'No changes detected';

  return updates
    .map((u) => {
      const action = u.from_value ? 'changed' : 'added';
      const fieldName = u.field.charAt(0).toUpperCase() + u.field.slice(1);
      return `${action} ${fieldName}: ${u.to}`;
    })
    .join(' · ');
}

function StatusIcon({ status, isPending }: { status: AckStatus; isPending?: boolean }) {
  if (isPending) {
    return <Loader2 className="h-3 w-3 animate-spin text-emerald-500/80" />;
  }

  switch (status) {
    case 'applied':
      return <Check className="h-3 w-3 text-emerald-500/80" />;
    case 'partial':
      return <AlertCircle className="h-3 w-3 text-zinc-500/80" />;
    case 'failed':
    case 'needs_clarification':
      return <AlertCircle className="h-3 w-3 text-red-500/80" />;
    case 'no_change':
      return <Minus className="h-3 w-3 text-zinc-500" />;
    default:
      return <Check className="h-3 w-3 text-zinc-500" />;
  }
}

function getMessage(status: AckStatus, updates: AckUpdate[], isPending?: boolean): string {
  if (isPending) return 'Building plan...';

  switch (status) {
    case 'applied':
      return updates.length > 0 ? `Applied: ${formatUpdates(updates)}` : 'Plan ready';
    case 'partial':
      return `Partial: ${formatUpdates(updates)}`;
    case 'no_change':
      return 'No changes needed';
    case 'needs_clarification':
      return 'Need more details';
    case 'failed':
      return 'Update failed';
    default:
      return formatUpdates(updates);
  }
}

export function SystemAckLine({ status, updates = [], isPending }: SystemAckLineProps) {
  const message = getMessage(status, updates, isPending);

  return (
    <div
      className={cn(
        'flex items-center gap-2 px-3 py-1.5',
        'text-xs text-zinc-400',
        'border-l-2',
        status === 'applied' && !isPending && 'border-emerald-500/50',
        status === 'partial' && 'border-zinc-500/50',
        status === 'failed' && 'border-red-500/50',
        status === 'needs_clarification' && 'border-red-500/50',
        isPending && 'border-emerald-500/50',
        status === 'no_change' && 'border-zinc-600'
      )}
    >
      <StatusIcon status={status} isPending={isPending} />
      <span className={cn(isPending && 'animate-pulse')}>{message}</span>
    </div>
  );
}

export default SystemAckLine;
