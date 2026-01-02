/**
 * Main comparison view showing two branches side-by-side.
 *
 * Layout:
 * - Desktop (lg+): Side-by-side 50/50 columns
 * - Mobile (< md): Stacked vertical layout
 *
 * Features:
 * - Exit button in header
 * - Diff badges showing differences
 * - Responsive layout
 */

import { X } from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';

import { BranchComparisonColumn } from './BranchComparisonColumn';
import { useComparisonMode } from './hooks/useComparisonMode';

type BranchComparisonViewProps = {
  tripInputs?: DocumentTripInputs | null;
  className?: string;
};

export const BranchComparisonView = memo(function BranchComparisonView({
  tripInputs,
  className,
}: BranchComparisonViewProps) {
  const {
    comparisonBranches,
    diff,
    exitComparisonMode,
    isComparisonReady,
  } = useComparisonMode();

  // Don't render if comparison not ready (need 2 branches selected)
  if (!isComparisonReady || !comparisonBranches) {
    return null;
  }

  const [firstBranch, secondBranch] = comparisonBranches;

  return (
    <div className={cn('flex flex-col', className)}>
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">
          Comparing Trip Options
        </h2>
        <button
          type="button"
          onClick={exitComparisonMode}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200"
          aria-label="Exit comparison mode"
        >
          <X className="h-4 w-4" />
          <span>Exit</span>
        </button>
      </div>

      {/* Comparison grid */}
      <div className="grid gap-4 md:grid-cols-2">
        <BranchComparisonColumn
          branch={firstBranch}
          tripInputs={tripInputs}
          isFirst={true}
        />
        <BranchComparisonColumn
          branch={secondBranch}
          tripInputs={tripInputs}
          isFirst={false}
          budgetDiff={diff?.budget}
          durationDiff={diff?.duration}
        />
      </div>

      {/* Summary section */}
      {diff && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-700">
            Quick Comparison
          </h3>
          <ul className="space-y-1 text-sm text-gray-600">
            {diff.budget && diff.budget.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Budget:</span>
                <span>
                  Option B is {diff.budget.value > 0 ? 'cheaper' : 'more expensive'} (
                  {diff.budget.formatted})
                </span>
              </li>
            )}
            {diff.duration && diff.duration.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Duration:</span>
                <span>
                  Option B is {diff.duration.value > 0 ? 'shorter' : 'longer'} (
                  {diff.duration.formatted})
                </span>
              </li>
            )}
            {diff.activityCount && diff.activityCount.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Activities:</span>
                <span>
                  Option B has {diff.activityCount.value < 0 ? 'more' : 'fewer'} options (
                  {diff.activityCount.formatted})
                </span>
              </li>
            )}
            {(!diff.budget || diff.budget.value === 0) &&
              (!diff.duration || diff.duration.value === 0) &&
              (!diff.activityCount || diff.activityCount.value === 0) && (
              <li className="text-gray-500">
                Both options are similar in budget, duration, and activities.
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
});
