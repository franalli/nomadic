/**
 * CollapsedMessageRow
 *
 * Compact display for acknowledged constraint update messages.
 * Shows status icon + summary + timestamp + expand caret.
 */

'use client';

import { AlertCircle, Check, ChevronDown, Minus } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { AckStatus, AckUpdate } from '@/types/chat';

interface CollapsedMessageRowProps {
  ackStatus: AckStatus;
  ackUpdates: AckUpdate[];
  summaryText?: string;
  timestamp?: string;
  isExpanded: boolean;
  onToggle: () => void;
}

/**
 * Generate summary text from ack updates
 * Format: "Updated: Destination -> Rome . Origin -> Dubai . Jan 21"
 */
function generateSummary(updates: AckUpdate[]): string {
  if (updates.length === 0) return 'No changes';

  const parts = updates.map((u) => {
    // Format field name nicely
    const fieldName = u.field.charAt(0).toUpperCase() + u.field.slice(1);
    return `${fieldName} = ${u.to}`;
  });

  return `Updated: ${parts.join(' · ')}`;
}

/**
 * Get status icon based on ack status
 */
function StatusIcon({ status }: { status: AckStatus }) {
  switch (status) {
    case 'applied':
      return <Check className="h-3.5 w-3.5 text-emerald-500/80" />;
    case 'partial':
      return <AlertCircle className="h-3.5 w-3.5 text-zinc-500/80" />;
    case 'no_change':
      return <Minus className="h-3.5 w-3.5 text-zinc-500" />;
    default:
      return <Check className="h-3.5 w-3.5 text-zinc-500" />;
  }
}

export function CollapsedMessageRow({
  ackStatus,
  ackUpdates,
  summaryText,
  timestamp,
  isExpanded,
  onToggle,
}: CollapsedMessageRowProps) {
  const summary = summaryText || generateSummary(ackUpdates);

  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        'w-full flex items-center gap-2 px-3 py-2 rounded-lg',
        'text-left text-xs transition-all duration-200',
        'hover:bg-zinc-800/40 group',
        isExpanded && 'bg-zinc-800/30'
      )}
    >
      {/* Status icon */}
      <div className="flex-shrink-0">
        <StatusIcon status={ackStatus} />
      </div>

      {/* Summary text */}
      <span className="flex-1 text-zinc-400 truncate">
        {summary}
      </span>

      {/* Timestamp (if provided) */}
      {timestamp && (
        <span className="flex-shrink-0 text-zinc-600 text-[10px]">
          {timestamp}
        </span>
      )}

      {/* Expand caret */}
      <ChevronDown
        className={cn(
          'h-3.5 w-3.5 text-zinc-600 transition-transform duration-200',
          'group-hover:text-zinc-400',
          isExpanded && 'rotate-180'
        )}
      />
    </button>
  );
}

export default CollapsedMessageRow;
