'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * AlternativesModal
 *
 * "Change Hotel/Flight" sheet that shows alternative options.
 * Current selection displayed at top, alternatives below with comparison indicators.
 *
 * @see docs/ux_unified_architecture.md Section I.B
 */

import { SlidersHorizontal } from 'lucide-react';
import { useMemo, useState } from 'react';

import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { AlternativeCard, CurrentSelectionCard } from './AlternativesModalParts';

// =============================================================================
// Types
// =============================================================================

interface AlternativesModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentTile: Tile | null;
  alternatives: Tile[];
  category: string;
  onSelect: (tile: Tile) => void;
  sortBy?: 'price' | 'rating' | 'name';
  onSortChange?: (sort: 'price' | 'rating' | 'name') => void;
}

type SortOption = 'price' | 'rating' | 'name';

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

  const sortedAlternatives = useMemo(() => {
    const sorted = [...alternatives];
    switch (sortBy) {
      case 'price':
        return sorted.sort((a, b) => (a.price_estimate ?? 0) - (b.price_estimate ?? 0));
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
        <SheetHeader className="border-b border-zinc-200 dark:border-white/10 pb-4">
          <SheetTitle className="text-zinc-900 dark:text-zinc-100">
            Change {category}
          </SheetTitle>
          <SheetClose />
        </SheetHeader>

        <div className="p-4 space-y-4">
          {currentTile && <CurrentSelectionCard tile={currentTile} />}

          {/* Sort Controls */}
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
            <span className="text-xs text-zinc-500 dark:text-zinc-400">Sort by:</span>
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
            <p className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wide font-medium">
              Alternatives ({sortedAlternatives.length})
            </p>

            {sortedAlternatives.length === 0 ? (
              <div className="p-4 text-center text-zinc-500 text-sm">
                No alternatives available
              </div>
            ) : (
              <div className="space-y-2">
                {sortedAlternatives.map((alt) => (
                  <AlternativeCard
                    key={alt.id}
                    alt={alt}
                    currentPrice={currentPrice}
                    currentRating={currentRating}
                    isCurrentlySelected={currentTile?.id === alt.id}
                    onSelect={onSelect}
                  />
                ))}
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
