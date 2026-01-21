/**
 * TileFilterBar
 *
 * Lightweight sort/filter controls for tiles in S2.
 * Frontend-only filtering over existing tile data.
 *
 * Features:
 * - Sort: Recommended / Price / Rating
 * - Toggle: Free cancellation only
 * - Budget ceiling: Under €X
 */

'use client';

import { Check, ChevronDown, SlidersHorizontal } from 'lucide-react';
import { memo, useCallback, useMemo, useRef, useState } from 'react';

import { cn } from '@/lib/utils';

export type SortOption = 'recommended' | 'price_low' | 'price_high' | 'rating';

export interface TileFilters {
  sort: SortOption;
  freeCancel: boolean;
  maxPrice: number | null;
}

export interface TileFilterBarProps {
  filters: TileFilters;
  onFiltersChange: (filters: TileFilters) => void;
  /** Currency symbol for price filter display */
  currency?: string;
  /** Max price in the current tile set (for slider reference) */
  maxPriceInSet?: number;
  /** Whether any filters are active (for visual indicator) */
  className?: string;
}

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: 'recommended', label: 'Recommended' },
  { value: 'price_low', label: 'Price: Low to High' },
  { value: 'price_high', label: 'Price: High to Low' },
  { value: 'rating', label: 'Rating' },
];

export const TileFilterBar = memo(function TileFilterBar({
  filters,
  onFiltersChange,
  currency = '$',
  maxPriceInSet,
  className,
}: TileFilterBarProps) {
  const [sortOpen, setSortOpen] = useState(false);
  const [priceOpen, setPriceOpen] = useState(false);
  const sortRef = useRef<HTMLDivElement>(null);
  const priceRef = useRef<HTMLDivElement>(null);

  // Close dropdowns when clicking outside
  const handleClickOutside = useCallback((e: MouseEvent) => {
    if (sortRef.current && !sortRef.current.contains(e.target as Node)) {
      setSortOpen(false);
    }
    if (priceRef.current && !priceRef.current.contains(e.target as Node)) {
      setPriceOpen(false);
    }
  }, []);

  // Add/remove click listener
  useState(() => {
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  });

  const handleSortChange = useCallback(
    (sort: SortOption) => {
      onFiltersChange({ ...filters, sort });
      setSortOpen(false);
    },
    [filters, onFiltersChange]
  );

  const handleFreeCancelToggle = useCallback(() => {
    onFiltersChange({ ...filters, freeCancel: !filters.freeCancel });
  }, [filters, onFiltersChange]);

  const handleMaxPriceChange = useCallback(
    (maxPrice: number | null) => {
      onFiltersChange({ ...filters, maxPrice });
      setPriceOpen(false);
    },
    [filters, onFiltersChange]
  );

  // Price presets based on max price in set
  const pricePresets = useMemo(() => {
    if (!maxPriceInSet) return [];
    const presets: number[] = [];
    // Generate 3-4 reasonable price points
    const step = Math.ceil(maxPriceInSet / 4 / 50) * 50; // Round to nearest 50
    for (let i = 1; i <= 3; i++) {
      const price = step * i;
      if (price < maxPriceInSet) {
        presets.push(price);
      }
    }
    return presets;
  }, [maxPriceInSet]);

  const currentSortLabel = SORT_OPTIONS.find((o) => o.value === filters.sort)?.label || 'Sort';
  const hasActiveFilters = filters.freeCancel || filters.maxPrice !== null;

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {/* Sort dropdown */}
      <div ref={sortRef} className="relative">
        <button
          type="button"
          onClick={() => setSortOpen(!sortOpen)}
          className={cn(
            'flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors',
            sortOpen
              ? 'border-amber-500/50 bg-amber-500/10 text-amber-400'
              : 'border-zinc-700/50 bg-zinc-800/50 text-zinc-400 hover:border-zinc-600'
          )}
        >
          <SlidersHorizontal className="h-3 w-3" />
          <span>{currentSortLabel}</span>
          <ChevronDown className={cn('h-3 w-3 transition-transform', sortOpen && 'rotate-180')} />
        </button>

        {sortOpen && (
          <div className="absolute left-0 top-full z-20 mt-1 min-w-[160px] rounded-lg border border-zinc-700 bg-zinc-800 py-1 shadow-lg">
            {SORT_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => handleSortChange(option.value)}
                className={cn(
                  'flex w-full items-center justify-between px-3 py-2 text-left text-xs transition-colors',
                  filters.sort === option.value
                    ? 'bg-amber-500/10 text-amber-400'
                    : 'text-zinc-300 hover:bg-zinc-700/50'
                )}
              >
                <span>{option.label}</span>
                {filters.sort === option.value && <Check className="h-3 w-3" />}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Free cancellation toggle */}
      <button
        type="button"
        onClick={handleFreeCancelToggle}
        className={cn(
          'flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors',
          filters.freeCancel
            ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400'
            : 'border-zinc-700/50 bg-zinc-800/50 text-zinc-400 hover:border-zinc-600'
        )}
      >
        {filters.freeCancel && <Check className="h-3 w-3" />}
        <span>Free cancellation</span>
      </button>

      {/* Price filter dropdown */}
      {pricePresets.length > 0 && (
        <div ref={priceRef} className="relative">
          <button
            type="button"
            onClick={() => setPriceOpen(!priceOpen)}
            className={cn(
              'flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors',
              filters.maxPrice !== null
                ? 'border-amber-500/50 bg-amber-500/10 text-amber-400'
                : priceOpen
                  ? 'border-zinc-600 bg-zinc-800/50 text-zinc-300'
                  : 'border-zinc-700/50 bg-zinc-800/50 text-zinc-400 hover:border-zinc-600'
            )}
          >
            <span>
              {filters.maxPrice !== null
                ? `Under ${currency}${filters.maxPrice.toLocaleString()}`
                : 'Max price'}
            </span>
            <ChevronDown className={cn('h-3 w-3 transition-transform', priceOpen && 'rotate-180')} />
          </button>

          {priceOpen && (
            <div className="absolute left-0 top-full z-20 mt-1 min-w-[140px] rounded-lg border border-zinc-700 bg-zinc-800 py-1 shadow-lg">
              <button
                type="button"
                onClick={() => handleMaxPriceChange(null)}
                className={cn(
                  'flex w-full items-center justify-between px-3 py-2 text-left text-xs transition-colors',
                  filters.maxPrice === null
                    ? 'bg-amber-500/10 text-amber-400'
                    : 'text-zinc-300 hover:bg-zinc-700/50'
                )}
              >
                <span>Any price</span>
                {filters.maxPrice === null && <Check className="h-3 w-3" />}
              </button>
              {pricePresets.map((price) => (
                <button
                  key={price}
                  type="button"
                  onClick={() => handleMaxPriceChange(price)}
                  className={cn(
                    'flex w-full items-center justify-between px-3 py-2 text-left text-xs transition-colors',
                    filters.maxPrice === price
                      ? 'bg-amber-500/10 text-amber-400'
                      : 'text-zinc-300 hover:bg-zinc-700/50'
                  )}
                >
                  <span>Under {currency}{price.toLocaleString()}</span>
                  {filters.maxPrice === price && <Check className="h-3 w-3" />}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Clear filters button (when active) */}
      {hasActiveFilters && (
        <button
          type="button"
          onClick={() => onFiltersChange({ sort: 'recommended', freeCancel: false, maxPrice: null })}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Clear
        </button>
      )}
    </div>
  );
});

export default TileFilterBar;
