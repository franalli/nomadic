/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * AlternativesModal
 *
 * "Change Hotel/Flight" sheet that shows alternative options.
 * Current selection displayed at top, alternatives below with comparison indicators.
 *
 * @see docs/ux_unified_architecture.md Section I.B
 */

'use client';

import {
  ArrowDown,
  ArrowUp,
  Check,
  Minus,
  SlidersHorizontal,
  Star,
} from 'lucide-react';
import Image from 'next/image';
import { memo, useCallback, useMemo, useState } from 'react';

import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { DS } from '@/lib/design-system';
import { formatPrice } from '@/lib/format-utils';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// Helper component for tile thumbnails with error fallback
const TileThumbnail = memo(function TileThumbnail({
  tile,
  size,
}: {
  tile: Tile;
  size: string;
}) {
  const [hasError, setHasError] = useState(false);
  const handleError = useCallback(() => setHasError(true), []);

  const placeholderUrl = placeholderImageForTile(tile);
  const imageSrc = hasError ? placeholderUrl : (tile.image_url || placeholderUrl);

  return (
    <Image
      src={imageSrc}
      alt={tile.title}
      fill
      className="object-cover"
      sizes={size}
      onError={handleError}
    />
  );
});

// =============================================================================
// Types
// =============================================================================

interface AlternativesModalProps {
  /** Whether modal is open */
  open: boolean;
  /** Close handler */
  onOpenChange: (open: boolean) => void;
  /** Currently selected tile */
  currentTile: Tile | null;
  /** Alternative options */
  alternatives: Tile[];
  /** Category label (e.g., "Hotel", "Flight") */
  category: string;
  /** Callback when user selects an alternative */
  onSelect: (tile: Tile) => void;
  /** Sort options */
  sortBy?: 'price' | 'rating' | 'name';
  onSortChange?: (sort: 'price' | 'rating' | 'name') => void;
}

type SortOption = 'price' | 'rating' | 'name';

// =============================================================================
// Helpers
// =============================================================================

function formatPriceOrDash(price: number | undefined): string {
  if (!price) return '\u2014';
  return formatPrice(price);
}

function getPriceDiff(
  current: number | undefined,
  alternative: number | undefined
): { value: number; label: string; type: 'cheaper' | 'more' | 'same' } | null {
  if (!current || !alternative) return null;
  const diff = alternative - current;
  if (Math.abs(diff) < 1) return { value: 0, label: 'Same price', type: 'same' };
  if (diff < 0) return { value: Math.abs(diff), label: `-$${Math.abs(diff)}`, type: 'cheaper' };
  return { value: diff, label: `+$${diff}`, type: 'more' };
}

function getRatingDiff(
  current: number | undefined,
  alternative: number | undefined
): { value: number; label: string; type: 'better' | 'worse' | 'same' } | null {
  if (!current || !alternative) return null;
  const diff = alternative - current;
  if (Math.abs(diff) < 0.1) return { value: 0, label: 'Same rating', type: 'same' };
  if (diff > 0)
    return { value: diff, label: `+${diff.toFixed(1)}`, type: 'better' };
  return { value: Math.abs(diff), label: `${diff.toFixed(1)}`, type: 'worse' };
}

// =============================================================================
// Component
// =============================================================================

export function AlternativesModal({
  open,
  onOpenChange,
  currentTile,
  alternatives,
  category,
  onSelect,
  sortBy: externalSortBy,
  onSortChange,
}: AlternativesModalProps) {
  const [internalSortBy, setInternalSortBy] = useState<SortOption>('price');
  const sortBy = externalSortBy ?? internalSortBy;

  const handleSortChange = (sort: SortOption) => {
    if (onSortChange) {
      onSortChange(sort);
    } else {
      setInternalSortBy(sort);
    }
  };

  // Sort alternatives
  const sortedAlternatives = useMemo(() => {
    const sorted = [...alternatives];
    switch (sortBy) {
      case 'price':
        return sorted.sort(
          (a, b) => (a.price_estimate ?? 0) - (b.price_estimate ?? 0)
        );
      case 'rating':
        return sorted.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
      case 'name':
        return sorted.sort((a, b) => a.title.localeCompare(b.title));
      default:
        return sorted;
    }
  }, [alternatives, sortBy]);

  const currentPrice = currentTile?.price_estimate;
  const currentRating = currentTile?.rating;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md overflow-y-auto bg-white dark:bg-zinc-900">
        <ModalErrorBoundary>
        <SheetHeader className="border-b border-zinc-200 dark:border-zinc-700/50 pb-4">
          <SheetTitle className="text-zinc-900 dark:text-zinc-100">
            Change {category}
          </SheetTitle>
          <SheetClose />
        </SheetHeader>

        <div className="p-4 space-y-4">
          {/* Current Selection */}
          {currentTile && (
            <div className="space-y-2">
              <p className="text-xs text-zinc-500 uppercase tracking-wide font-medium">
                Current Selection
              </p>
              <div className="flex gap-3 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
                {/* Thumbnail */}
                <div className="relative w-16 h-16 rounded-lg overflow-hidden flex-shrink-0">
                  <TileThumbnail tile={currentTile} size="64px" />
                  <div className="absolute inset-0 flex items-center justify-center bg-emerald-500/40">
                    <Check className="w-6 h-6 text-white" />
                  </div>
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <h4 className="font-semibold text-sm text-zinc-800 dark:text-zinc-200 line-clamp-1">
                    {currentTile.title}
                  </h4>
                  <div className="flex items-center gap-2 mt-1">
                    {currentTile.rating && (
                      <div className="flex items-center gap-0.5">
                        <Star className="w-3 h-3 text-zinc-500 dark:text-zinc-300 fill-current" />
                        <span className="text-xs text-zinc-700 dark:text-zinc-300">
                          {currentTile.rating.toFixed(1)}
                        </span>
                      </div>
                    )}
                    {currentTile.price_estimate && (
                      <span className="text-xs font-medium text-emerald-400">
                        {formatPriceOrDash(currentTile.price_estimate)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Sort Controls */}
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="w-4 h-4 text-zinc-500" />
            <span className="text-xs text-zinc-500">Sort by:</span>
            <div className="flex gap-1">
              {(['price', 'rating', 'name'] as SortOption[]).map((option) => (
                <button
                  key={option}
                  onClick={() => handleSortChange(option)}
                  className={cn(
                    'px-2 py-1 rounded text-xs font-medium transition-colors',
                    sortBy === option
                      ? 'bg-zinc-100 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-200'
                      : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
                  )}
                >
                  {option.charAt(0).toUpperCase() + option.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Alternatives List */}
          <div className="space-y-2">
            <p className="text-xs text-zinc-500 uppercase tracking-wide font-medium">
              Alternatives ({sortedAlternatives.length})
            </p>

            {sortedAlternatives.length === 0 ? (
              <div className="p-4 text-center text-zinc-500 text-sm">
                No alternatives available
              </div>
            ) : (
              <div className="space-y-2">
                {sortedAlternatives.map((alt) => {
                  const priceDiff = getPriceDiff(currentPrice, alt.price_estimate);
                  const ratingDiff = getRatingDiff(currentRating, alt.rating);
                  const isCurrentlySelected = currentTile?.id === alt.id;

                  return (
                    <button
                      key={alt.id}
                      onClick={() => !isCurrentlySelected && onSelect(alt)}
                      disabled={isCurrentlySelected}
                      className={cn(
                        'w-full flex gap-3 p-3 rounded-xl text-left transition-colors',
                        isCurrentlySelected
                          ? 'bg-zinc-50 dark:bg-zinc-800/30 opacity-50 cursor-not-allowed'
                          : 'bg-zinc-100 dark:bg-zinc-800/50 hover:bg-zinc-200 dark:hover:bg-zinc-700/50 border border-zinc-200 dark:border-zinc-700/30 hover:border-zinc-300 dark:hover:border-zinc-600/50'
                      )}
                    >
                      {/* Thumbnail */}
                      <div className="relative w-14 h-14 rounded-lg overflow-hidden flex-shrink-0">
                        <TileThumbnail tile={alt} size="56px" />
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <h4 className="font-medium text-sm text-zinc-800 dark:text-zinc-200 line-clamp-1">
                          {alt.title}
                        </h4>

                        {/* Rating */}
                        <div className="flex items-center gap-2 mt-1">
                          {alt.rating && (
                            <div className="flex items-center gap-0.5">
                              <Star className="w-3 h-3 text-zinc-500 dark:text-zinc-300 fill-current" />
                              <span className="text-xs text-zinc-700 dark:text-zinc-300">
                                {alt.rating.toFixed(1)}
                              </span>
                            </div>
                          )}

                          {/* Rating diff badge */}
                          {ratingDiff && ratingDiff.type !== 'same' && (
                            <span
                              className={cn(
                                `flex items-center gap-0.5 ${DS.textSize.micro} font-medium px-1 py-0.5 rounded`,
                                ratingDiff.type === 'better'
                                  ? 'bg-emerald-500/20 text-emerald-400'
                                  : 'bg-zinc-200 text-zinc-700 dark:bg-zinc-700/50 dark:text-zinc-300'
                              )}
                            >
                              {ratingDiff.type === 'better' ? (
                                <ArrowUp className="w-2.5 h-2.5" />
                              ) : (
                                <ArrowDown className="w-2.5 h-2.5" />
                              )}
                              {ratingDiff.label}
                            </span>
                          )}
                        </div>

                        {/* Price row */}
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                            {formatPriceOrDash(alt.price_estimate)}
                          </span>

                          {/* Price diff badge */}
                          {priceDiff && priceDiff.type !== 'same' && (
                            <span
                              className={cn(
                                `flex items-center gap-0.5 ${DS.textSize.micro} font-medium px-1 py-0.5 rounded`,
                                priceDiff.type === 'cheaper'
                                  ? 'bg-emerald-500/20 text-emerald-400'
                                  : 'bg-rose-500/20 text-rose-400'
                              )}
                            >
                              {priceDiff.type === 'cheaper' ? (
                                <Minus className="w-2.5 h-2.5" />
                              ) : null}
                              {priceDiff.label}
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
        </ModalErrorBoundary>
      </SheetContent>
    </Sheet>
  );
}

export default AlternativesModal;
