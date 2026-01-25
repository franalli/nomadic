/**
 * CollapsedSetupSummary
 *
 * Single collapsed block replacing Setup assistant messages.
 * Shows: "Setup complete: Dubai · Jan 25-Feb 1 · 1 adult"
 * Expandable to show Configuration Snapshot (audit trail).
 */

'use client';

import { ChevronDown, MessageSquare } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';
import type { ChatMessage } from '@/types/chat';
import type { DocumentTripInputs } from '@/types/document';

// =============================================================================
// ConfigurationSnapshot - Displays trip inputs as key-value pairs
// =============================================================================

interface ConfigurationSnapshotProps {
  tripInputs: DocumentTripInputs;
  executedTopics?: string[];
}

/**
 * Format ISO date string to human-readable format (e.g., "Jan 26, 2026")
 */
function formatDate(isoDate: string | null | undefined): string | null {
  if (!isoDate) return null;
  try {
    const date = new Date(isoDate);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return isoDate; // Fallback to raw string if parsing fails
  }
}

/**
 * Format budget with currency symbol
 */
function formatBudget(budget: number | null | undefined, currency?: string): string | null {
  if (!budget) return null;
  const currencySymbol = currency === 'EUR' ? '€' : currency === 'GBP' ? '£' : '$';
  return `${currencySymbol}${budget.toLocaleString()}`;
}

/**
 * Format travelers count
 */
function formatTravelers(adults: number | null | undefined, children: number | null | undefined): string {
  const parts: string[] = [];
  if (adults) {
    parts.push(`${adults} Adult${adults > 1 ? 's' : ''}`);
  }
  if (children) {
    parts.push(`${children} Child${children > 1 ? 'ren' : ''}`);
  }
  return parts.length > 0 ? parts.join(', ') : '1 Adult';
}

function ConfigurationSnapshot({ tripInputs, executedTopics }: ConfigurationSnapshotProps) {
  // Build key-value entries
  const entries: Array<{ label: string; value: string }> = [];

  // Destination
  if (tripInputs.destination) {
    entries.push({
      label: 'Destination',
      value: tripInputs.destination,
    });
  }

  // Origin (if set)
  if (tripInputs.origin) {
    entries.push({
      label: 'Origin',
      value: tripInputs.origin,
    });
  }

  // Dates
  const startDate = formatDate(tripInputs.start_date);
  const endDate = formatDate(tripInputs.end_date);
  if (startDate && endDate) {
    entries.push({
      label: 'Dates',
      value: `${startDate} – ${endDate}`,
    });
  } else if (startDate) {
    entries.push({
      label: 'Start',
      value: startDate,
    });
  } else if (tripInputs.date_flex && tripInputs.trip_duration) {
    entries.push({
      label: 'Dates',
      value: `Flexible, ${tripInputs.trip_duration} days`,
    });
  }

  // Budget (if set)
  const budgetStr = formatBudget(tripInputs.budget, tripInputs.currency || 'USD');
  if (budgetStr) {
    entries.push({
      label: 'Budget',
      value: budgetStr,
    });
  }

  // Travelers
  entries.push({
    label: 'Travelers',
    value: formatTravelers(tripInputs.adults, tripInputs.children),
  });

  // Active Topics/Agents
  if (executedTopics?.length) {
    entries.push({
      label: 'Topics',
      value: executedTopics.map((t) => t.charAt(0).toUpperCase() + t.slice(1)).join(', '),
    });
  }

  return (
    <div
      className={cn(
        'mt-2 ml-4 pl-3 border-l-2 border-zinc-800/50',
        'space-y-1.5 animate-in slide-in-from-top-2 duration-200'
      )}
    >
      <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-2">
        Configuration Snapshot
      </div>
      {entries.map((entry) => (
        <div key={entry.label} className="flex items-baseline gap-2 text-xs">
          <span className="text-zinc-500 min-w-[80px]">{entry.label}</span>
          <span className="text-zinc-300">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

// =============================================================================
// CollapsedSetupSummary - Main component
// =============================================================================

interface CollapsedSetupSummaryProps {
  summaryText: string;
  originalMessages?: ChatMessage[];
  // Configuration snapshot for audit trail (prioritized over originalMessages)
  tripInputsSnapshot?: DocumentTripInputs;
  executedTopicsSnapshot?: string[];
}

export function CollapsedSetupSummary({
  summaryText,
  originalMessages = [],
  tripInputsSnapshot,
  executedTopicsSnapshot,
}: CollapsedSetupSummaryProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Handle click: toggle expand AND scroll right panel to top
  // This reinforces the connection between "Inputs" (left) and "Outputs" (right)
  const handleClick = () => {
    setIsExpanded(!isExpanded);
    // Scroll the right panel (plan-panel) to the top
    const planPanel = document.getElementById('plan-panel');
    if (planPanel) {
      planPanel.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  return (
    <div className="my-4 relative">
      {/* Visual divider line above - "chapter break" between Setup and Plan */}
      <div className="absolute -top-2 left-0 right-0 flex items-center gap-2">
        <div className="flex-1 h-px bg-gradient-to-r from-transparent via-zinc-700/60 to-transparent" />
      </div>

      {/* Collapsed header */}
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          'w-full flex items-center gap-2 px-3 py-2 rounded-lg',
          'text-left text-xs transition-all duration-200',
          'bg-zinc-800/40 hover:bg-zinc-800/60',
          'border border-zinc-700/40',
          'group'
        )}
      >
        <MessageSquare className="h-3.5 w-3.5 text-zinc-500 flex-shrink-0" />
        <span className="flex-1 text-zinc-400 truncate">{summaryText}</span>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-zinc-600 transition-transform duration-200',
            'group-hover:text-zinc-400',
            isExpanded && 'rotate-180'
          )}
        />
      </button>

      {/* Expanded content - prioritize Configuration Snapshot over original messages */}
      {isExpanded && tripInputsSnapshot && (
        <ConfigurationSnapshot
          tripInputs={tripInputsSnapshot}
          executedTopics={executedTopicsSnapshot}
        />
      )}

      {/* Fallback to original messages if no snapshot (backward compatibility) */}
      {isExpanded && !tripInputsSnapshot && originalMessages.length > 0 && (
        <div
          className={cn(
            'mt-2 ml-4 pl-3 border-l-2 border-zinc-800/50',
            'space-y-2 animate-in slide-in-from-top-2 duration-200'
          )}
        >
          {originalMessages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'text-xs',
                msg.role === 'user' ? 'text-zinc-300' : 'text-zinc-500'
              )}
            >
              <span className="text-zinc-600 font-medium">
                {msg.role === 'user' ? 'You: ' : 'Assistant: '}
              </span>
              {msg.content}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default CollapsedSetupSummary;
