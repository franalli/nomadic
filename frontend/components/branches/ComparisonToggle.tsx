/**
 * Toggle button to enter/exit trip comparison mode.
 *
 * - Only visible when 2+ branches exist
 * - Shows "Select 2 trips to compare" when active but not yet ready
 * - Provides visual feedback on selection count
 */

import { Maximize2, Minimize2 } from 'lucide-react';

import { cn } from '@/lib/utils';

import { useComparisonMode } from './hooks/useComparisonMode';

type ComparisonToggleProps = {
  className?: string;
};

export function ComparisonToggle({ className }: ComparisonToggleProps) {
  const {
    isComparisonMode,
    canCompare,
    isComparisonReady,
    selectedCount,
    toggleComparisonMode,
    exitComparisonMode,
  } = useComparisonMode();

  // Don't render if can't compare (< 2 branches)
  if (!canCompare) return null;

  const handleClick = () => {
    if (isComparisonMode) {
      exitComparisonMode();
    } else {
      toggleComparisonMode();
    }
  };

  // Determine button text and style
  const buttonText = isComparisonMode
    ? isComparisonReady
      ? 'Exit Compare'
      : `Select ${2 - selectedCount} more`
    : 'Compare';

  const Icon = isComparisonMode ? Minimize2 : Maximize2;

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-pressed={isComparisonMode}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
        isComparisonMode
          ? 'bg-indigo-600 text-white hover:bg-indigo-700'
          : 'bg-gray-100 text-gray-700 hover:bg-gray-200',
        className
      )}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      <span>{buttonText}</span>
      {isComparisonMode && !isComparisonReady && (
        <span className="ml-1 rounded-full bg-white/20 px-1.5 py-0.5 text-xs">
          {selectedCount}/2
        </span>
      )}
    </button>
  );
}
