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
import { useUIStore } from '@/state/uiStore';
import type { DocumentBranch } from '@/types/document';
import type { Tile } from '@/types/tile';

/**
 * Difference between two values with direction.
 */
export type ValueDiff = {
  value: number;
  direction: 'positive' | 'negative' | 'neutral';
  formatted: string;
  /** Percentage difference (e.g., 15 for "15% cheaper") */
  percentage?: number;
  /** Formatted percentage (e.g., "15% cheaper") */
  percentageFormatted?: string;
};

/**
 * Per-day rate information for budget comparison.
 */
export type PerDayRate = {
  baseRate: number;
  compareRate: number;
  formatted: string; // e.g., "$150/day vs $175/day"
  rateLabel: string; // e.g., "$150/day"
  compareRateLabel: string; // e.g., "$175/day"
};

/**
 * Selected tile information for a branch (Tier 9: comparison enhancement).
 */
export type SelectedTileInfo = {
  stay: Tile | null;
  flight: Tile | null;
  activities: Tile[];
  totalCost: number;
  formattedCost: string;
  hasSelections: boolean;
};

/**
 * Computed differences between two branches.
 */
export type BranchDiff = {
  budget: ValueDiff | null;
  duration: ValueDiff | null;
  stayCount: ValueDiff | null;
  activityCount: ValueDiff | null;
  /** Per-day budget rate comparison */
  perDayRate: PerDayRate | null;
  /** Actual cost from selected tiles (Tier 9) */
  actualCost: ValueDiff | null;
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
 * Create budget diff with currency formatting and percentage.
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

  // Calculate percentage difference relative to base
  const percentage = baseBudget > 0 ? Math.round((Math.abs(diff) / baseBudget) * 100) : 0;
  const percentageFormatted = diff > 0
    ? `${percentage}% cheaper`
    : `${percentage}% more`;

  return {
    value: diff,
    direction: diff > 0 ? 'positive' : 'negative',
    formatted: diff > 0 ? `Saves ${absFormatted}` : `+${absFormatted}`,
    percentage,
    percentageFormatted,
  };
}

/**
 * Get selected tile information for a branch (Tier 9: comparison enhancement).
 */
function getSelectedTileInfo(
  branch: DocumentBranch,
  tilesPool: Record<string, Tile>,
  currency: string = 'USD'
): SelectedTileInfo {
  const selections = branch.selections;

  const stay = selections.stay ? tilesPool[selections.stay] ?? null : null;
  const flight = selections.flight ? tilesPool[selections.flight] ?? null : null;
  const activities = selections.activities
    .map((id) => tilesPool[id])
    .filter((t): t is Tile => t != null);

  // Calculate total cost from selected tiles
  let totalCost = 0;
  if (stay?.price_estimate) totalCost += stay.price_estimate;
  if (flight?.price_estimate) totalCost += flight.price_estimate;
  for (const activity of activities) {
    if (activity.price_estimate) totalCost += activity.price_estimate;
  }

  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  });

  const hasSelections = stay != null || flight != null || activities.length > 0;

  return {
    stay,
    flight,
    activities,
    totalCost,
    formattedCost: totalCost > 0 ? formatter.format(totalCost) : '—',
    hasSelections,
  };
}

/**
 * Calculate per-day budget rate for comparison.
 */
function calculatePerDayRate(
  baseBudget: number | null | undefined,
  compareBudget: number | null | undefined,
  baseDuration: number | null,
  compareDuration: number | null,
  currency: string = 'USD'
): PerDayRate | null {
  if (baseBudget == null || compareBudget == null) return null;
  if (baseDuration == null || compareDuration == null) return null;
  if (baseDuration <= 0 || compareDuration <= 0) return null;

  const baseRate = Math.round(baseBudget / baseDuration);
  const compareRate = Math.round(compareBudget / compareDuration);

  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  });

  const rateLabel = `${formatter.format(baseRate)}/day`;
  const compareRateLabel = `${formatter.format(compareRate)}/day`;

  return {
    baseRate,
    compareRate,
    formatted: `${rateLabel} vs ${compareRateLabel}`,
    rateLabel,
    compareRateLabel,
  };
}

/**
 * Compute all differences between two branches.
 * Diffs are computed relative to the first branch (base).
 */
function computeBranchDiff(
  baseBranch: DocumentBranch,
  compareBranch: DocumentBranch,
  tilesPool: Record<string, Tile>
): BranchDiff {
  const currency = compareBranch.currency || baseBranch.currency || 'USD';

  // Budget diff (lower is better)
  const budget = createBudgetDiff(
    baseBranch.budget,
    compareBranch.budget,
    currency
  );

  // Duration diff in nights
  const baseDuration = calculateDuration(baseBranch.start_date, baseBranch.end_date);
  const compareDuration = calculateDuration(compareBranch.start_date, compareBranch.end_date);
  const duration = createDiff(baseDuration, compareDuration, ' nights', false);

  // Per-day rate comparison
  const perDayRate = calculatePerDayRate(
    baseBranch.budget,
    compareBranch.budget,
    baseDuration,
    compareDuration,
    currency
  );

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

  // Tier 9: Actual cost from selected tiles (more precise than budget)
  const baseSelectedInfo = getSelectedTileInfo(baseBranch, tilesPool, currency);
  const compareSelectedInfo = getSelectedTileInfo(compareBranch, tilesPool, currency);

  const actualCost =
    baseSelectedInfo.totalCost > 0 && compareSelectedInfo.totalCost > 0
      ? createBudgetDiff(baseSelectedInfo.totalCost, compareSelectedInfo.totalCost, currency)
      : null;

  return { budget, duration, stayCount, activityCount, perDayRate, actualCost };
}

/**
 * Hook for managing comparison mode.
 *
 * Uses useUIStore for comparison mode state (separated from document data).
 * Uses useDocumentStore for document/branch data.
 */
export function useComparisonMode() {
  // Document state from document store
  const document = useDocumentStore((state) => state.document);

  // UI state from UI store (separated for cleaner state management)
  const isComparisonMode = useUIStore((state) => state.isComparisonMode);
  const comparisonBranchIds = useUIStore((state) => state.comparisonBranchIds);

  // UI actions from UI store
  const setComparisonMode = useUIStore((state) => state.setComparisonMode);
  const toggleBranchForComparison = useUIStore((state) => state.toggleBranchForComparison);
  const exitComparisonMode = useUIStore((state) => state.exitComparisonMode);

  // Get branches and tiles pool for comparison
  const branches = document?.branches ?? [];
  const tilesPool = document?.tiles ?? {};

  // Get the two branches being compared
  const comparisonBranches = useMemo(() => {
    if (!comparisonBranchIds) return null;

    const [firstId, secondId] = comparisonBranchIds;
    const first = branches.find((b) => b.id === firstId);
    const second = branches.find((b) => b.id === secondId);

    if (!first || !second) return null;

    return [first, second] as const;
  }, [comparisonBranchIds, branches]);

  // Compute differences between branches (Tier 9: includes actual cost from tiles)
  const diff = useMemo(() => {
    if (!comparisonBranches) return null;
    const [first, second] = comparisonBranches;
    return computeBranchDiff(first, second, tilesPool);
  }, [comparisonBranches, tilesPool]);

  // Tier 9: Get selected tile info for each branch in comparison
  const selectedTilesInfo = useMemo(() => {
    if (!comparisonBranches) return null;
    const [first, second] = comparisonBranches;
    const currency = second.currency || first.currency || 'USD';
    return {
      first: getSelectedTileInfo(first, tilesPool, currency),
      second: getSelectedTileInfo(second, tilesPool, currency),
    };
  }, [comparisonBranches, tilesPool]);

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
    /** Tier 9: Selected tile info for both branches */
    selectedTilesInfo,

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
