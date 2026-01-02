/**
 * Hook for managing trip comparison mode.
 *
 * Provides:
 * - Comparison state from store
 * - Computed differences between branches (budget, duration)
 * - Actions for toggling/selecting branches
 */

import { useMemo } from 'react';

import { useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch } from '@/types/document';

/**
 * Difference between two values with direction.
 */
export type ValueDiff = {
  value: number;
  direction: 'positive' | 'negative' | 'neutral';
  formatted: string;
};

/**
 * Computed differences between two branches.
 */
export type BranchDiff = {
  budget: ValueDiff | null;
  duration: ValueDiff | null;
  stayCount: ValueDiff | null;
  activityCount: ValueDiff | null;
};

/**
 * Parse ISO date string to Date object.
 */
function parseDate(dateStr: string | null | undefined): Date | null {
  if (!dateStr) return null;
  const parsed = new Date(dateStr);
  return isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Calculate trip duration in nights.
 */
function calculateDuration(
  startDate: string | null | undefined,
  endDate: string | null | undefined
): number | null {
  const start = parseDate(startDate);
  const end = parseDate(endDate);
  if (!start || !end) return null;

  const diffTime = end.getTime() - start.getTime();
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  return diffDays > 0 ? diffDays : null;
}

/**
 * Create a ValueDiff comparing two values.
 * Positive direction means second value is lower/better (e.g., cheaper, shorter).
 */
function createDiff(
  baseValue: number | null,
  compareValue: number | null,
  unit: string,
  lowerIsBetter = true
): ValueDiff | null {
  if (baseValue === null || compareValue === null) return null;

  const diff = baseValue - compareValue;
  if (diff === 0) {
    return { value: 0, direction: 'neutral', formatted: 'Same' };
  }

  const direction = lowerIsBetter
    ? (diff > 0 ? 'positive' : 'negative')
    : (diff < 0 ? 'positive' : 'negative');

  const absValue = Math.abs(diff);
  const sign = diff > 0 ? '-' : '+';

  return {
    value: diff,
    direction,
    formatted: `${sign}${absValue}${unit}`,
  };
}

/**
 * Create budget diff with currency formatting.
 */
function createBudgetDiff(
  baseBudget: number | null | undefined,
  compareBudget: number | null | undefined,
  currency: string = 'USD'
): ValueDiff | null {
  if (baseBudget == null || compareBudget == null) return null;

  const diff = baseBudget - compareBudget;
  if (diff === 0) {
    return { value: 0, direction: 'neutral', formatted: 'Same' };
  }

  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  });

  const absFormatted = formatter.format(Math.abs(diff));

  return {
    value: diff,
    direction: diff > 0 ? 'positive' : 'negative',
    formatted: diff > 0 ? `Saves ${absFormatted}` : `+${absFormatted}`,
  };
}

/**
 * Compute all differences between two branches.
 * Diffs are computed relative to the first branch (base).
 */
function computeBranchDiff(
  baseBranch: DocumentBranch,
  compareBranch: DocumentBranch
): BranchDiff {
  // Budget diff (lower is better)
  const budget = createBudgetDiff(
    baseBranch.budget,
    compareBranch.budget,
    compareBranch.currency || baseBranch.currency || 'USD'
  );

  // Duration diff in nights
  const baseDuration = calculateDuration(baseBranch.start_date, baseBranch.end_date);
  const compareDuration = calculateDuration(compareBranch.start_date, compareBranch.end_date);
  const duration = createDiff(baseDuration, compareDuration, ' nights', false);

  // Stay count diff (more options is neutral, just informational)
  const stayCount = createDiff(
    baseBranch.tiles.stays.length,
    compareBranch.tiles.stays.length,
    ' stays',
    false
  );

  // Activity count diff (more is typically better)
  const activityCount = createDiff(
    baseBranch.tiles.activities.length,
    compareBranch.tiles.activities.length,
    ' activities',
    false
  );

  return { budget, duration, stayCount, activityCount };
}

/**
 * Hook for managing comparison mode.
 */
export function useComparisonMode() {
  // Store state
  const document = useDocumentStore((state) => state.document);
  const isComparisonMode = useDocumentStore((state) => state.isComparisonMode);
  const comparisonBranchIds = useDocumentStore((state) => state.comparisonBranchIds);

  // Store actions
  const setComparisonMode = useDocumentStore((state) => state.setComparisonMode);
  const toggleBranchForComparison = useDocumentStore((state) => state.toggleBranchForComparison);
  const exitComparisonMode = useDocumentStore((state) => state.exitComparisonMode);

  // Get branches for comparison
  const branches = document?.branches ?? [];

  // Get the two branches being compared
  const comparisonBranches = useMemo(() => {
    if (!comparisonBranchIds) return null;

    const [firstId, secondId] = comparisonBranchIds;
    const first = branches.find((b) => b.id === firstId);
    const second = branches.find((b) => b.id === secondId);

    if (!first || !second) return null;

    return [first, second] as const;
  }, [comparisonBranchIds, branches]);

  // Compute differences between branches
  const diff = useMemo(() => {
    if (!comparisonBranches) return null;
    const [first, second] = comparisonBranches;
    return computeBranchDiff(first, second);
  }, [comparisonBranches]);

  // Check if a branch is selected for comparison
  const isBranchInComparison = (branchId: string): boolean => {
    if (!comparisonBranchIds) return false;
    return comparisonBranchIds.includes(branchId);
  };

  // Can enter comparison mode (need 2+ branches)
  const canCompare = branches.length >= 2;

  // Is ready to show comparison (2 branches selected)
  const isComparisonReady = comparisonBranches !== null;

  // Number of branches selected
  const selectedCount = comparisonBranchIds ? 2 : (isComparisonMode ? 1 : 0);

  return {
    // State
    isComparisonMode,
    comparisonBranchIds,
    comparisonBranches,
    canCompare,
    isComparisonReady,
    selectedCount,

    // Computed
    diff,

    // Helpers
    isBranchInComparison,

    // Actions
    setComparisonMode,
    toggleBranchForComparison,
    exitComparisonMode,

    // Toggle comparison mode on/off
    toggleComparisonMode: () => setComparisonMode(!isComparisonMode),
  };
}

export type UseComparisonModeReturn = ReturnType<typeof useComparisonMode>;
