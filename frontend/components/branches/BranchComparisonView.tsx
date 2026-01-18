/**
 * Main comparison view showing two branches side-by-side.
 *
 * Layout:
 * - Desktop (md+): Side-by-side 50/50 columns
 * - Mobile (< md): Horizontal swipe carousel with snap scrolling (Tier 9)
 *
 * Features:
 * - Exit button in header
 * - Diff badges showing differences
 * - Responsive layout
 * - Mobile swipe gestures with scroll snap
 * - Scroll position indicators on mobile
 */

import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import { memo, useCallback, useEffect,useRef, useState } from 'react';

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
    selectedTilesInfo,
    exitComparisonMode,
    isComparisonReady,
  } = useComparisonMode();

  // Tier 9: Mobile swipe state - hooks must be called before any early returns
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [activeMobileIndex, setActiveMobileIndex] = useState(0);

  // Tier 10.8: Mobile swipe hint - show once per session
  const [showSwipeHint, setShowSwipeHint] = useState(false);

  // Check localStorage for swipe hint seen status
  useEffect(() => {
    if (!isComparisonReady) return;
    const hasSeen = localStorage.getItem('comparison-swipe-hint-seen');
    if (!hasSeen) {
      setShowSwipeHint(true);
      // Auto-dismiss after 3 seconds
      const timer = setTimeout(() => {
        setShowSwipeHint(false);
        localStorage.setItem('comparison-swipe-hint-seen', 'true');
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [isComparisonReady]);

  // Dismiss hint on any scroll
  const dismissHint = useCallback(() => {
    if (showSwipeHint) {
      setShowSwipeHint(false);
      localStorage.setItem('comparison-swipe-hint-seen', 'true');
    }
  }, [showSwipeHint]);

  // Handle scroll snap position change on mobile
  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const scrollLeft = container.scrollLeft;
    const cardWidth = container.offsetWidth;
    const newIndex = Math.round(scrollLeft / cardWidth);
    setActiveMobileIndex(newIndex);

    // Tier 10.8: Dismiss hint on scroll
    dismissHint();
  }, [dismissHint]);

  // Listen for scroll events on mobile container
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  // Scroll to specific card on mobile
  const scrollToCard = useCallback((index: number) => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const cardWidth = container.offsetWidth;
    container.scrollTo({ left: index * cardWidth, behavior: 'smooth' });
  }, []);

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
          Comparing Plans
        </h2>
        {/* Tier 9: Larger touch target for exit button */}
        <button
          type="button"
          onClick={exitComparisonMode}
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 transition-colors touch-manipulation hover:bg-gray-200 active:bg-gray-300 min-h-[44px]"
          aria-label="Exit comparison mode"
        >
          <X className="h-4 w-4" />
          <span>Exit</span>
        </button>
      </div>

      {/* Tier 10.8: Mobile swipe hint - shown once on first comparison */}
      {showSwipeHint && (
        <div className="flex items-center justify-center gap-2 mb-3 md:hidden animate-pulse">
          <ChevronLeft className="h-4 w-4 text-indigo-500" />
          <span className="text-sm text-indigo-600 font-medium">Swipe to compare</span>
          <ChevronRight className="h-4 w-4 text-indigo-500" />
        </div>
      )}

      {/* Mobile scroll indicators (Tier 9) */}
      <div className="flex justify-center gap-2 mb-3 md:hidden">
        {[0, 1].map((index) => (
          <button
            key={index}
            type="button"
            onClick={() => scrollToCard(index)}
            className={cn(
              'h-2 rounded-full transition-all touch-manipulation',
              activeMobileIndex === index
                ? 'w-6 bg-indigo-600'
                : 'w-2 bg-gray-300 hover:bg-gray-400'
            )}
            aria-label={`View ${index === 0 ? firstBranch.destinations[0] || 'Option A' : secondBranch.destinations[0] || 'Option B'}`}
          />
        ))}
      </div>

      {/* Comparison grid - Desktop: side-by-side, Mobile: horizontal scroll snap */}
      <div
        ref={scrollContainerRef}
        className="grid gap-4 md:grid-cols-2 md:overflow-visible overflow-x-auto snap-x snap-mandatory scroll-smooth md:snap-none scrollbar-hide"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        {/* Tier 9: snap-start for mobile scroll snap, min-w-full ensures full-width on mobile */}
        <BranchComparisonColumn
          branch={firstBranch}
          tripInputs={tripInputs}
          isFirst={true}
          perDayRate={diff?.perDayRate}
          selectedTiles={selectedTilesInfo?.first}
          className="min-w-full md:min-w-0 snap-start md:snap-align-none"
        />
        <BranchComparisonColumn
          branch={secondBranch}
          tripInputs={tripInputs}
          isFirst={false}
          budgetDiff={diff?.budget}
          durationDiff={diff?.duration}
          stayCountDiff={diff?.stayCount}
          activityCountDiff={diff?.activityCount}
          perDayRate={diff?.perDayRate}
          selectedTiles={selectedTilesInfo?.second}
          actualCostDiff={diff?.actualCost}
          className="min-w-full md:min-w-0 snap-start md:snap-align-none"
        />
      </div>

      {/* Summary section */}
      {diff && (
        <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h3 className="mb-2 text-sm font-medium text-gray-700">
            Quick Comparison: {firstBranch.destinations[0] || 'Option A'} vs {secondBranch.destinations[0] || 'Option B'}
          </h3>
          <ul className="space-y-2 text-sm text-gray-600">
            {/* Tier 9: Show actual cost from selected tiles if available */}
            {diff.actualCost && diff.actualCost.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Actual Cost:</span>
                <span>
                  {secondBranch.destinations[0] || 'Option B'} is {diff.actualCost.percentageFormatted || diff.actualCost.formatted} (from selected items)
                </span>
              </li>
            )}
            {diff.budget && diff.budget.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Budget:</span>
                <span>
                  {secondBranch.destinations[0] || 'Option B'} is {diff.budget.percentageFormatted || diff.budget.formatted}
                  {diff.perDayRate && (
                    <span className="text-gray-500 ml-1">({diff.perDayRate.formatted})</span>
                  )}
                </span>
              </li>
            )}
            {diff.duration && diff.duration.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Duration:</span>
                <span>
                  {secondBranch.destinations[0] || 'Option B'} is {diff.duration.value > 0 ? 'shorter' : 'longer'} (
                  {diff.duration.formatted})
                </span>
              </li>
            )}
            {diff.stayCount && diff.stayCount.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Stays:</span>
                <span>
                  {secondBranch.destinations[0] || 'Option B'} has {Math.abs(diff.stayCount.value)} {diff.stayCount.value < 0 ? 'more' : 'fewer'} stay option{Math.abs(diff.stayCount.value) !== 1 ? 's' : ''}
                </span>
              </li>
            )}
            {diff.activityCount && diff.activityCount.value !== 0 && (
              <li className="flex items-center gap-2">
                <span className="font-medium">Activities:</span>
                <span>
                  {secondBranch.destinations[0] || 'Option B'} has {Math.abs(diff.activityCount.value)} {diff.activityCount.value < 0 ? 'more' : 'fewer'} activit{Math.abs(diff.activityCount.value) !== 1 ? 'ies' : 'y'}
                </span>
              </li>
            )}
            {(!diff.budget || diff.budget.value === 0) &&
              (!diff.duration || diff.duration.value === 0) &&
              (!diff.stayCount || diff.stayCount.value === 0) &&
              (!diff.activityCount || diff.activityCount.value === 0) && (
              <li className="text-gray-500">
                Both trips are similar in budget, duration, and options.
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
});
