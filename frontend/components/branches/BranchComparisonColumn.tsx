/**
 * Single column in the comparison view showing one branch.
 *
 * Displays:
 * - Title/destination
 * - Budget with optional diff badge
 * - Duration with optional diff badge
 * - Description/highlights
 * - Tile counts (stays, flights, activities)
 */

import { Banknote, Calendar, Home, MapPin, Plane, Sparkles } from 'lucide-react';
import { memo } from 'react';

import { cn, formatBudgetDisplay } from '@/lib/utils';
import type { DocumentBranch, DocumentTripInputs } from '@/types/document';

import { OptionalDiffBadge } from './ComparisonDiffBadge';
import type { ValueDiff } from './hooks/useComparisonMode';

const DAY_IN_MS = 1000 * 60 * 60 * 24;

function formatDuration(start?: string | null, end?: string | null): string | null {
  if (!start || !end) return null;
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null;
  const diffMs = endDate.getTime() - startDate.getTime();
  if (diffMs < 0) return null;
  const days = Math.max(1, Math.round(diffMs / DAY_IN_MS));
  return `${days} night${days === 1 ? '' : 's'}`;
}

function formatDateRange(start?: string | null, end?: string | null): string | null {
  if (!start || !end) return null;
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return null;

  const formatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  });

  return `${formatter.format(startDate)} - ${formatter.format(endDate)}`;
}

type BranchComparisonColumnProps = {
  branch: DocumentBranch;
  tripInputs?: DocumentTripInputs | null;
  isFirst?: boolean;
  budgetDiff?: ValueDiff | null;
  durationDiff?: ValueDiff | null;
  className?: string;
};

export const BranchComparisonColumn = memo(function BranchComparisonColumn({
  branch,
  tripInputs,
  isFirst = false,
  budgetDiff,
  durationDiff,
  className,
}: BranchComparisonColumnProps) {
  // Resolve values from branch or trip inputs
  const destinations = branch.destinations.length > 0
    ? branch.destinations
    : tripInputs?.destinations ?? [];
  const origin = branch.origin ?? tripInputs?.origin ?? null;
  const startDate = branch.start_date ?? tripInputs?.start_date ?? null;
  const endDate = branch.end_date ?? tripInputs?.end_date ?? null;
  const budget = branch.budget ?? tripInputs?.budget ?? null;
  const currency = branch.currency ?? tripInputs?.currency ?? 'USD';

  const duration = formatDuration(startDate, endDate);
  const dateRange = formatDateRange(startDate, endDate);
  const budgetLabel = formatBudgetDisplay(budget, currency);

  const stayCount = branch.tiles.stays.length;
  const flightCount = branch.tiles.flights.length;
  const activityCount = branch.tiles.activities.length;

  return (
    <div
      className={cn(
        'flex flex-col rounded-xl border bg-white p-4 shadow-sm',
        isFirst ? 'border-indigo-200 bg-indigo-50/30' : 'border-gray-200',
        className
      )}
    >
      {/* Header with label */}
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          {isFirst ? 'Option A' : 'Option B'}
        </span>
        {branch.is_primary && (
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
            Primary
          </span>
        )}
      </div>

      {/* Destination */}
      <div className="mb-4">
        <div className="flex items-start gap-2">
          <MapPin className="mt-0.5 h-5 w-5 flex-shrink-0 text-gray-400" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900">
              {destinations.join(', ') || 'Destination TBD'}
            </h3>
            {origin && (
              <p className="text-sm text-gray-500">From {origin}</p>
            )}
          </div>
        </div>
      </div>

      {/* Description */}
      {branch.description && (
        <p className="mb-4 text-sm text-gray-600 line-clamp-3">
          {branch.description}
        </p>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
        {/* Budget */}
        <div className="rounded-lg bg-gray-50 p-3">
          <div className="flex items-center gap-1.5 text-gray-500">
            <Banknote className="h-4 w-4" />
            <span className="text-xs font-medium">Budget</span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">
              {budgetLabel || '—'}
            </span>
            {!isFirst && <OptionalDiffBadge diff={budgetDiff} />}
          </div>
        </div>

        {/* Duration */}
        <div className="rounded-lg bg-gray-50 p-3">
          <div className="flex items-center gap-1.5 text-gray-500">
            <Calendar className="h-4 w-4" />
            <span className="text-xs font-medium">Duration</span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-900">
              {duration || '—'}
            </span>
            {!isFirst && <OptionalDiffBadge diff={durationDiff} />}
          </div>
          {dateRange && (
            <p className="mt-0.5 text-xs text-gray-500">{dateRange}</p>
          )}
        </div>
      </div>

      {/* Tile counts */}
      <div className="mt-4 flex items-center gap-4 border-t border-gray-100 pt-4">
        <div className="flex items-center gap-1.5 text-gray-600">
          <Home className="h-4 w-4" />
          <span className="text-sm">{stayCount} stay{stayCount !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex items-center gap-1.5 text-gray-600">
          <Plane className="h-4 w-4" />
          <span className="text-sm">{flightCount} flight{flightCount !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex items-center gap-1.5 text-gray-600">
          <Sparkles className="h-4 w-4" />
          <span className="text-sm">{activityCount} activit{activityCount !== 1 ? 'ies' : 'y'}</span>
        </div>
      </div>
    </div>
  );
});
