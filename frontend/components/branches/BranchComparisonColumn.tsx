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

import { Banknote, Calendar, Check, Home, MapPin, Plane, Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { memo } from 'react';

import { cn, formatBudgetDisplay } from '@/lib/utils';
import type { DocumentBranch, DocumentTripInputs } from '@/types/document';

import { OptionalDiffBadge } from './ComparisonDiffBadge';
import type { PerDayRate, SelectedTileInfo, ValueDiff } from './hooks/useComparisonMode';

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
  stayCountDiff?: ValueDiff | null;
  activityCountDiff?: ValueDiff | null;
  perDayRate?: PerDayRate | null;
  /** Tier 9: Selected tiles info for this branch */
  selectedTiles?: SelectedTileInfo | null;
  /** Tier 9: Actual cost diff from selected tiles */
  actualCostDiff?: ValueDiff | null;
  className?: string;
};

export const BranchComparisonColumn = memo(function BranchComparisonColumn({
  branch,
  tripInputs,
  isFirst = false,
  budgetDiff,
  durationDiff,
  stayCountDiff,
  activityCountDiff,
  perDayRate,
  selectedTiles,
  actualCostDiff,
  className,
}: BranchComparisonColumnProps) {
  // Resolve values from branch or trip inputs
  const destination = branch.destination ?? tripInputs?.destination ?? null;
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
      {/* Header with semantic label */}
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          {destination ? `${destination} Trip` : (isFirst ? 'Option A' : 'Option B')}
        </span>
        <div className="flex items-center gap-2">
          {branch.is_primary && (
            <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
              Primary
            </span>
          )}
          {!isFirst && budgetDiff && budgetDiff.percentageFormatted && (
            <span className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
              budgetDiff.direction === 'positive' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
            )}>
              {budgetDiff.direction === 'positive' ? <TrendingDown className="h-3 w-3" /> : <TrendingUp className="h-3 w-3" />}
              {budgetDiff.percentageFormatted}
            </span>
          )}
        </div>
      </div>

      {/* Destination */}
      <div className="mb-4">
        <div className="flex items-start gap-2">
          <MapPin className="mt-0.5 h-5 w-5 flex-shrink-0 text-gray-400" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900">
              {destination || 'Destination TBD'}
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
          {/* Per-day rate */}
          {perDayRate && (
            <p className="mt-0.5 text-xs text-gray-500">
              {isFirst ? perDayRate.rateLabel : perDayRate.compareRateLabel}
            </p>
          )}
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

      {/* Tile counts with diff badges */}
      <div className="mt-4 flex flex-wrap items-center gap-4 border-t border-gray-100 pt-4">
        <div className="flex items-center gap-1.5 text-gray-600">
          <Home className="h-4 w-4" />
          <span className="text-sm">{stayCount} stay{stayCount !== 1 ? 's' : ''}</span>
          {!isFirst && <OptionalDiffBadge diff={stayCountDiff} size="sm" />}
        </div>
        <div className="flex items-center gap-1.5 text-gray-600">
          <Plane className="h-4 w-4" />
          <span className="text-sm">{flightCount} flight{flightCount !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex items-center gap-1.5 text-gray-600">
          <Sparkles className="h-4 w-4" />
          <span className="text-sm">{activityCount} activit{activityCount !== 1 ? 'ies' : 'y'}</span>
          {!isFirst && <OptionalDiffBadge diff={activityCountDiff} size="sm" />}
        </div>
      </div>

      {/* Tier 9: Selected tiles section - shows what's actually booked */}
      {selectedTiles && selectedTiles.hasSelections && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
              Selected Items
            </span>
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-gray-900">
                {selectedTiles.formattedCost}
              </span>
              {!isFirst && <OptionalDiffBadge diff={actualCostDiff} />}
            </div>
          </div>
          <div className="space-y-2">
            {selectedTiles.stay && (
              <div className="flex items-center gap-2 rounded-md bg-green-50 px-2 py-1.5">
                <Check className="h-3.5 w-3.5 text-green-600" />
                <Home className="h-3.5 w-3.5 text-gray-500" />
                <span className="flex-1 truncate text-xs text-gray-700">
                  {selectedTiles.stay.title}
                </span>
                {selectedTiles.stay.price_estimate && (
                  <span className="text-xs font-medium text-gray-600">
                    {new Intl.NumberFormat('en-US', { style: 'currency', currency: selectedTiles.stay.currency || 'USD', maximumFractionDigits: 0 }).format(selectedTiles.stay.price_estimate)}
                  </span>
                )}
              </div>
            )}
            {selectedTiles.flight && (
              <div className="flex items-center gap-2 rounded-md bg-green-50 px-2 py-1.5">
                <Check className="h-3.5 w-3.5 text-green-600" />
                <Plane className="h-3.5 w-3.5 text-gray-500" />
                <span className="flex-1 truncate text-xs text-gray-700">
                  {selectedTiles.flight.title}
                </span>
                {selectedTiles.flight.price_estimate && (
                  <span className="text-xs font-medium text-gray-600">
                    {new Intl.NumberFormat('en-US', { style: 'currency', currency: selectedTiles.flight.currency || 'USD', maximumFractionDigits: 0 }).format(selectedTiles.flight.price_estimate)}
                  </span>
                )}
              </div>
            )}
            {selectedTiles.activities.slice(0, 2).map((activity) => (
              <div key={activity.id} className="flex items-center gap-2 rounded-md bg-green-50 px-2 py-1.5">
                <Check className="h-3.5 w-3.5 text-green-600" />
                <Sparkles className="h-3.5 w-3.5 text-gray-500" />
                <span className="flex-1 truncate text-xs text-gray-700">
                  {activity.title}
                </span>
                {activity.price_estimate && (
                  <span className="text-xs font-medium text-gray-600">
                    {new Intl.NumberFormat('en-US', { style: 'currency', currency: activity.currency || 'USD', maximumFractionDigits: 0 }).format(activity.price_estimate)}
                  </span>
                )}
              </div>
            ))}
            {selectedTiles.activities.length > 2 && (
              <p className="text-xs text-gray-500 pl-7">
                +{selectedTiles.activities.length - 2} more activit{selectedTiles.activities.length - 2 === 1 ? 'y' : 'ies'}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
});
