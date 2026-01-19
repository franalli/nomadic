'use client';

import { memo } from 'react';

import { cn } from '@/lib/utils';
import { formatBudget, formatDateRange } from '@/lib/plan-transform';
import type { DocumentBranch, DocumentTripInputs } from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// DocumentHeader Component
// ─────────────────────────────────────────────────────────────────────────────

interface DocumentHeaderProps {
  branch: DocumentBranch;
  tripInputs: DocumentTripInputs;
  totalEstimate?: number | null;
  isUpdating?: boolean;
  className?: string;
}

function DocumentHeaderInner({
  branch,
  tripInputs,
  totalEstimate,
  isUpdating = false,
  className,
}: DocumentHeaderProps) {
  // Build summary line parts
  const origin = tripInputs.origin || branch.origin;
  const destination = branch.destinations?.[0] || tripInputs.destinations?.[0];
  const dateRange = formatDateRange(
    branch.start_date || tripInputs.start_date,
    branch.end_date || tripInputs.end_date
  );
  const budget = formatBudget(
    tripInputs.budget ?? branch.budget,
    tripInputs.currency ?? branch.currency ?? 'EUR'
  );

  // Build route string
  const route = origin && destination
    ? `${origin} → ${destination}`
    : destination || origin || null;

  // Combine into summary
  const summaryParts = [route, dateRange, budget].filter(Boolean);
  const summaryLine = summaryParts.length > 0 ? summaryParts.join(' · ') : null;

  // Budget comparison (only show if both are available)
  const budgetAmount = tripInputs.budget ?? branch.budget;
  const showBudgetComparison = budgetAmount != null && totalEstimate != null;
  const isWithinBudget = showBudgetComparison && totalEstimate! <= budgetAmount!;
  const budgetDifference = showBudgetComparison
    ? Math.abs(totalEstimate! - budgetAmount!)
    : 0;

  return (
    <div className={cn('space-y-2', className)}>
      {/* Summary line */}
      {summaryLine && (
        <p className="text-sm text-muted-foreground">
          {summaryLine}
        </p>
      )}

      {/* Updating status */}
      {isUpdating && (
        <p className="text-sm text-muted-foreground">
          Updating plan...
        </p>
      )}

      {/* Total estimate with budget comparison */}
      {totalEstimate != null && (
        <div className="pt-2 border-t border-border/30">
          <p className="text-sm text-foreground">
            <span className="font-medium">Estimated total cost:</span>{' '}
            {formatBudget(totalEstimate, tripInputs.currency ?? 'EUR')}
          </p>
          {showBudgetComparison && (
            <p className="text-xs text-muted-foreground mt-0.5">
              {isWithinBudget
                ? `Within budget (${formatBudget(budgetAmount, tripInputs.currency ?? 'EUR')})`
                : `Exceeds budget by ${formatBudget(budgetDifference, tripInputs.currency ?? 'EUR')}`}
            </p>
          )}
        </div>
      )}

      {/* Branch description if available */}
      {branch.description && !isUpdating && (
        <p className="text-sm text-muted-foreground">
          {branch.description}
        </p>
      )}

      {/* Vibe/focus if available from strategy */}
      {branch.vibe && (
        <p className="text-xs text-muted-foreground italic">
          {branch.vibe}
        </p>
      )}
    </div>
  );
}

export const DocumentHeader = memo(DocumentHeaderInner);
