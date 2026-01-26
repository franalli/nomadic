/**
 * BookingSection
 *
 * Conditional tiles section for the plan view.
 * - S3: Full "Booking options" grid with tabs
 * - S2 with tiles + strategy content: "Options to choose from" with MiniCards
 * - S2 generating: "Searching deals…" or "Refreshing deals…" placeholder
 * - S2 without tiles: Minimal placeholder
 * - Other states: Not rendered
 */

'use client';

import { ChevronDown, ChevronUp, Lock } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { MiniCard, MiniCardSkeleton } from '@/components/tiles/MiniCard';
import { TileDetailsModal } from '@/components/tiles/TileDetailsModal';
import { TileFilterBar, type TileFilters } from '@/components/tiles/TileFilterBar';
import { TilesGrid } from '@/components/tiles/TilesGrid';
import { chipActive, chipBase, chipInactive } from '@/lib/chipStyles';
import { getTotalTileCount, selectTilesByType } from '@/lib/tileSelectors';
import { cn } from '@/lib/utils';
import type { GenerationState, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { canShowBookingTiles, canShowTilesPreview, isGenerating } from './planStateHelpers';

// Category types for S2 preview
type TileCategory = 'stays' | 'flights' | 'activities';

export interface BookingSectionProps {
  state: PlanViewState;
  tiles: Record<string, Tile> | Tile[];
  generation?: GenerationState | null;
  hasStrategyContent?: boolean;
  /** Set of saved tile IDs (from shortlist) */
  savedTileIds?: Set<string>;
  /** Callback when user clicks Save on a tile */
  onSaveTile?: (tile: Tile) => void;
  /** Callback to open a sheet (for "set trip length" link) */
  onOpenSheet?: (sheet: SheetType) => void;
}

export function BookingSection({
  state,
  tiles,
  generation,
  hasStrategyContent,
  savedTileIds = new Set(),
  onSaveTile,
  onOpenSheet,
}: BookingSectionProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [activeCategory, setActiveCategory] = useState<TileCategory>('stays');
  const [selectedTile, setSelectedTile] = useState<Tile | null>(null);
  const [filters, setFilters] = useState<TileFilters>({
    sort: 'recommended',
    freeCancel: false,
    maxPrice: null,
  });

  // Convert tiles to array if needed
  const tileArray = Array.isArray(tiles) ? tiles : Object.values(tiles);
  const tilesByType = selectTilesByType(tiles);
  const totalTiles = getTotalTileCount(tilesByType);

  // Compute category counts
  const stayTiles = tileArray.filter(t => t.type === 'hotel' || t.type === 'stay' || t.type === 'accommodation');
  const flightTiles = tileArray.filter(t => t.type === 'flight');
  const activityTiles = tileArray.filter(t => t.type === 'activity' || t.type === 'experience' || t.type === 'tour' || t.type === 'attraction');

  const categoryCounts = {
    stays: stayTiles.length,
    flights: flightTiles.length,
    activities: activityTiles.length,
  };

  // Apply filters and sorting to tiles
  const applyFilters = useCallback((tilesToFilter: Tile[]): Tile[] => {
    let result = [...tilesToFilter];

    // Filter: free cancellation
    if (filters.freeCancel) {
      result = result.filter((t) => t.is_refundable === true);
    }

    // Filter: max price
    if (filters.maxPrice !== null) {
      result = result.filter((t) => {
        const price = t.total_inclusive ?? t.price_estimate;
        return price != null && price <= filters.maxPrice!;
      });
    }

    // Sort
    switch (filters.sort) {
      case 'price_low':
        result.sort((a, b) => {
          const aPrice = a.total_inclusive ?? a.price_estimate ?? Infinity;
          const bPrice = b.total_inclusive ?? b.price_estimate ?? Infinity;
          return aPrice - bPrice;
        });
        break;
      case 'price_high':
        result.sort((a, b) => {
          const aPrice = a.total_inclusive ?? a.price_estimate ?? 0;
          const bPrice = b.total_inclusive ?? b.price_estimate ?? 0;
          return bPrice - aPrice;
        });
        break;
      case 'rating':
        result.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
        break;
      // 'recommended' keeps original order
    }

    return result;
  }, [filters]);

  // Get max price for current category (for filter presets)
  const maxPriceInCategory = useMemo(() => {
    const categoryTiles = activeCategory === 'stays' ? stayTiles
      : activeCategory === 'flights' ? flightTiles
      : activityTiles;
    const prices = categoryTiles
      .map((t) => t.total_inclusive ?? t.price_estimate)
      .filter((p): p is number => p != null);
    return prices.length > 0 ? Math.max(...prices) : undefined;
  }, [activeCategory, stayTiles, flightTiles, activityTiles]);

  // Get currency from first tile with price
  const currency = useMemo(() => {
    const tile = tileArray.find((t) => t.currency);
    return tile?.currency === 'EUR' ? '€' : tile?.currency === 'GBP' ? '£' : '$';
  }, [tileArray]);

  // Get filtered tiles for active category (max 6 for S2 preview)
  const getFilteredCategoryTiles = useCallback((category: TileCategory): Tile[] => {
    const baseTiles = category === 'stays' ? stayTiles
      : category === 'flights' ? flightTiles
      : activityTiles;
    return applyFilters(baseTiles).slice(0, 6);
  }, [stayTiles, flightTiles, activityTiles, applyFilters]);

  const previewTiles = getFilteredCategoryTiles(activeCategory);
  const categoryTotalCount = categoryCounts[activeCategory];
  const filteredCount = applyFilters(
    activeCategory === 'stays' ? stayTiles
      : activeCategory === 'flights' ? flightTiles
      : activityTiles
  ).length;
  const remainingCount = Math.max(0, filteredCount - previewTiles.length);

  // Handlers for MiniCard actions
  const handleDetailsClick = useCallback((tile: Tile) => {
    setSelectedTile(tile);
  }, []);

  const handleSaveClick = useCallback(
    (tile: Tile) => {
      onSaveTile?.(tile);
    },
    [onSaveTile]
  );

  const handleCloseModal = useCallback(() => {
    setSelectedTile(null);
  }, []);

  // S2 with tiles + strategy content: "Options to choose from" with MiniCards
  if (canShowTilesPreview(state, totalTiles, generation, hasStrategyContent) && totalTiles > 0) {
    return (
      <>
        <div id="booking-section" className="border-t border-border">
          {/* Header */}
          <div className="px-4 pt-4 pb-1">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium text-card-foreground">
                Options to choose from
              </h3>
              {savedTileIds.size > 0 && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/15 text-amber-700 dark:text-amber-400">
                  {savedTileIds.size} in trip
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Compare and save favorites.
            </p>
            {/* Section-level lock message */}
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground mt-2">
              <Lock className="h-3 w-3" />
              <span>
                Booking links unlock after you{' '}
                {onOpenSheet ? (
                  <button
                    type="button"
                    onClick={() => onOpenSheet('dates')}
                    className="text-amber-600 hover:text-amber-500 dark:text-amber-500 dark:hover:text-amber-400 underline underline-offset-2"
                  >
                    set trip dates
                  </button>
                ) : (
                  'set trip dates'
                )}{' '}
                and create your itinerary.
              </span>
            </p>
          </div>

          {/* Category chips with counts */}
          <div className="flex gap-2 px-4 py-3">
            {(['stays', 'flights', 'activities'] as const).map((category) => {
              const count = categoryCounts[category];
              const isActive = activeCategory === category;
              const isDisabled = count === 0;

              return (
                <button
                  key={category}
                  onClick={() => {
                    if (!isDisabled) {
                      setActiveCategory(category);
                    }
                  }}
                  disabled={isDisabled}
                  className={cn(
                    chipBase,
                    'font-medium',
                    isActive
                      ? chipActive
                      : isDisabled
                        ? 'bg-muted/30 text-muted-foreground/50 border-border/30 cursor-not-allowed'
                        : chipInactive
                  )}
                >
                  {category.charAt(0).toUpperCase() + category.slice(1)} ({count})
                </button>
              );
            })}
          </div>

          {/* Filter bar */}
          <div className="px-4 pb-2">
            <TileFilterBar
              filters={filters}
              onFiltersChange={setFilters}
              currency={currency}
              maxPriceInSet={maxPriceInCategory}
            />
          </div>

          {/* Expand/collapse toggle */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex w-full items-center justify-between px-4 py-2 text-sm transition-colors hover:bg-muted"
          >
            <span className="text-muted-foreground">
              {isExpanded ? 'Hide' : 'Show'} {filteredCount} {activeCategory}
              {filteredCount !== categoryTotalCount && (
                <span className="text-muted-foreground/70"> (of {categoryTotalCount})</span>
              )}
            </span>
            {isExpanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>

          {/* MiniCards grid */}
          {isExpanded && (
            <div className="px-4 pb-4 space-y-2">
              {previewTiles.length > 0 ? (
                <>
                  {previewTiles.map((tile) => (
                    <MiniCard
                      key={tile.id}
                      tile={tile}
                      isSaved={savedTileIds.has(tile.id)}
                      onDetailsClick={handleDetailsClick}
                      onSaveClick={handleSaveClick}
                    />
                  ))}
                  {remainingCount > 0 && (
                    <p className="text-xs text-muted-foreground pt-2">
                      +{remainingCount} more {activeCategory} available
                    </p>
                  )}
                </>
              ) : filteredCount === 0 && categoryTotalCount > 0 ? (
                <div className="text-xs text-muted-foreground py-2">
                  <p>No {activeCategory} match your filters.</p>
                  <button
                    type="button"
                    onClick={() => setFilters({ sort: 'recommended', freeCancel: false, maxPrice: null })}
                    className="text-amber-600 hover:text-amber-500 dark:text-amber-500 dark:hover:text-amber-400 mt-1"
                  >
                    Clear filters
                  </button>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground py-2">
                  No {activeCategory} found yet.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Details modal */}
        <TileDetailsModal
          tile={selectedTile}
          isOpen={selectedTile !== null}
          isSaved={selectedTile ? savedTileIds.has(selectedTile.id) : false}
          onClose={handleCloseModal}
          onSaveClick={handleSaveClick}
        />
      </>
    );
  }

  // S2 generating: skeleton loaders (YC Demo polish)
  if (state.startsWith('S2_') && isGenerating(generation)) {
    const message = totalTiles > 0 ? 'Refreshing deals…' : 'Searching deals…';
    return (
      <div id="booking-section" className="px-4 py-2 space-y-3 animate-in fade-in duration-500">
        <p className="text-xs text-muted-foreground">{message}</p>
        <MiniCardSkeleton />
        <MiniCardSkeleton />
        <MiniCardSkeleton />
      </div>
    );
  }

  // S2 without tiles or without strategy content: minimal placeholder
  if (state.startsWith('S2_')) {
    return (
      <div id="booking-section" className="px-4 py-2">
        <p className="text-xs text-muted-foreground/70">
          Booking options appear after itinerary.
        </p>
      </div>
    );
  }

  // S3: Full "Booking options" section with tabs
  if (canShowBookingTiles(state)) {
    if (totalTiles === 0) {
      return (
        <div id="booking-section" className="border-t border-border p-4">
          <p className="text-sm text-muted-foreground">No booking options available yet.</p>
        </div>
      );
    }

    return (
      <div id="booking-section" className="border-t border-border p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-card-foreground">Booking options</h3>
            <span className="text-xs text-muted-foreground">({totalTiles})</span>
            {savedTileIds.size > 0 && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/15 text-amber-700 dark:text-amber-400">
                {savedTileIds.size} in trip
              </span>
            )}
          </div>
          <span className="text-xs text-muted-foreground">Prices from partners</span>
        </div>
        <TilesGrid tiles={tileArray} hideTabSwitcher={false} savedTileIds={savedTileIds} />
      </div>
    );
  }

  // Other states: don't render (no empty padding)
  return null;
}

export default BookingSection;
