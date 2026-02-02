'use client';

import { AlertCircle, ChevronDown, Plane, RotateCcw, Sparkles, TentTree } from 'lucide-react';
import { type ElementType, memo, useEffect, useMemo, useState } from 'react';

import { TileCard } from '@/components/tiles/TileCard';
import { Skeleton } from '@/components/ui/skeleton';
import { isActivityType, isFlightType } from '@/lib/utils';
import type { DocumentBranch } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

// Skeleton component for tile cards (Tier 10.6: Exported for branch switch loading)
export const TileCardSkeleton = memo(function TileCardSkeleton() {
  return (
    <div className="rounded-2xl border border-border/40 bg-card overflow-hidden shadow-lg">
      {/* Image skeleton */}
      <Skeleton className="h-32 w-full rounded-none" />
      {/* Content skeleton */}
      <div className="p-3 space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
        <div className="flex justify-between items-center pt-2">
          <Skeleton className="h-5 w-20" />
          <Skeleton className="h-8 w-8 rounded-full" />
        </div>
      </div>
    </div>
  );
});

export type TileTabKey = 'stays' | 'flights' | 'activities';

export const TAB_CONFIG: Record<
  TileTabKey,
  { label: string; icon: ElementType; emptyMessage: string }
> = {
  stays: {
    label: 'Stays',
    icon: TentTree,
    emptyMessage: 'No stays found. Adjust constraints.',
  },
  flights: {
    label: 'Flights',
    icon: Plane,
    emptyMessage: 'No flights found. Adjust constraints.',
  },
  activities: {
    label: 'Activities',
    icon: Sparkles,
    emptyMessage: 'Activities load when matches are found.',
  },
};

export const resolveTabForTile = (tile: Tile): TileTabKey => {
  const type = tile.type || '';
  if (isFlightType(type)) return 'flights';
  if (isActivityType(type)) return 'activities';
  return 'stays';
};

type TilesGridProps = {
  tiles: Tile[];
  activeBranch?: DocumentBranch | null;
  selectedTiles?: TileSelection;
  onTileToggle?: (tile: Tile, tab: TileTabKey) => void;
  forcedTab?: TileTabKey;
  hideTabSwitcher?: boolean;
  /** Show skeleton loaders while tiles are loading */
  isLoading?: boolean;
  /** Indicates tiles failed to load (show error state with retry) */
  loadError?: boolean;
  /** Callback to retry loading tiles */
  onRetry?: () => void;
  /** Callback to show toast notification when tile is selected (Tier 10.19) */
  onSelectionToast?: (message: string) => void;
  /** Set of tile IDs that were saved/shortlisted (show first with badge) */
  savedTileIds?: Set<string>;
  /** Callback to open category-wide stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
};

// Default number of tiles to show before "View All" expansion
const DEFAULT_SHOW_COUNT = 3;

export const TilesGrid = memo(function TilesGrid({
  tiles,
  activeBranch,
  selectedTiles,
  onTileToggle,
  forcedTab,
  hideTabSwitcher = false,
  isLoading = false,
  loadError = false,
  onRetry,
  onSelectionToast,
  savedTileIds = new Set(),
  onOpenStaysSettings,
}: TilesGridProps) {
  const [activeTab, setActiveTab] = useState<TileTabKey>(forcedTab ?? 'stays');
  const [isExpanded, setIsExpanded] = useState(false);
  const effectiveTab = forcedTab ?? activeTab;

  // Reset expansion when tab changes (progressive disclosure per category)
  useEffect(() => {
    setIsExpanded(false);
  }, [effectiveTab]);

  const tabCounts = useMemo(() => {
    return tiles.reduce(
      (acc, tile) => {
        const tab = resolveTabForTile(tile);
        acc[tab] += 1;
        return acc;
      },
      { stays: 0, flights: 0, activities: 0 } as Record<TileTabKey, number>
    );
  }, [tiles]);

  const filteredTiles = useMemo(() => {
    const filtered = tiles.filter((tile) => resolveTabForTile(tile) === effectiveTab);
    // Sort saved tiles first
    if (savedTileIds.size > 0) {
      return [...filtered].sort((a, b) => {
        const aIsSaved = savedTileIds.has(a.id) ? 1 : 0;
        const bIsSaved = savedTileIds.has(b.id) ? 1 : 0;
        return bIsSaved - aIsSaved; // Saved items first
      });
    }
    return filtered;
  }, [effectiveTab, tiles, savedTileIds]);

  // Progressive disclosure: Show limited tiles by default, expand on click
  const displayedTiles = useMemo(() => {
    if (isExpanded) return filteredTiles;
    return filteredTiles.slice(0, DEFAULT_SHOW_COUNT);
  }, [filteredTiles, isExpanded]);

  const hiddenCount = filteredTiles.length - displayedTiles.length;

  const priceSummary = useMemo(() => {
    const priceValues = tiles
      .map((tile) => tile.price_estimate)
      .filter((value): value is number => typeof value === 'number');
    const currency = tiles.find((tile) => tile.currency)?.currency ?? '';
    if (!priceValues.length) return null;
    const min = Math.min(...priceValues);
    const max = Math.max(...priceValues);
    const formattedMin = Math.round(min).toLocaleString();
    const formattedMax = Math.round(max).toLocaleString();
    if (min === max) return `${formattedMin} ${currency}`.trim();
    return `${formattedMin} - ${formattedMax} ${currency}`.trim();
  }, [tiles]);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">
        Prices and availability from partners.
      </p>
      {!hideTabSwitcher && (
        <div className="space-y-2">
          {priceSummary && (
            <div className="text-muted-foreground flex items-center gap-3 text-sm">
              <div className="bg-primary/10 text-primary inline-flex items-center gap-2 rounded-full px-3 py-1 font-semibold">
                {priceSummary}
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-4 pb-1">
            {(Object.keys(TAB_CONFIG) as TileTabKey[]).map((tab) => {
              const Icon = TAB_CONFIG[tab].icon;
              const isActive = tab === effectiveTab;
              return (
                <button
                  key={tab}
                  type="button"
                  onClick={() => {
                    if (forcedTab) return;
                    setActiveTab(tab);
                  }}
                  className={`focus-visible:outline-primary group relative flex items-center gap-2 border-b-2 pb-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${
                    isActive
                      ? 'border-primary text-primary'
                      : 'text-muted-foreground hover:text-foreground border-transparent'
                  } ${forcedTab ? 'cursor-default opacity-60' : ''}`}
                  aria-disabled={Boolean(forcedTab)}
                  aria-pressed={isActive}
                >
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-full border transition ${
                      isActive
                        ? 'border-primary/30 bg-primary/10 text-primary'
                        : 'border-border/70 text-muted-foreground bg-card'
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <span>{TAB_CONFIG[tab].label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      isActive
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-muted text-muted-foreground'
                    }`}
                  >
                    {tabCounts[tab]}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {isLoading ? (
          // Show skeleton loaders while loading
          <>
            <TileCardSkeleton />
            <TileCardSkeleton />
            <TileCardSkeleton />
          </>
        ) : loadError ? (
          // Show error state with retry button
          <div className="border-destructive/30 bg-destructive/5 text-foreground rounded-xl border border-dashed p-4 shadow-inner sm:col-span-2 xl:col-span-3">
            <div className="flex items-center gap-3">
              <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-medium">Failed to load {TAB_CONFIG[effectiveTab].label.toLowerCase()}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  There was a problem fetching options. Please try again.
                </p>
              </div>
              {onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  <RotateCcw className="h-3 w-3" />
                  Retry
                </button>
              )}
            </div>
          </div>
        ) : filteredTiles.length === 0 ? (
          <div className="border-accent/30 bg-accent/5 text-muted-foreground rounded-xl border border-dashed p-4 text-sm shadow-inner sm:col-span-2 xl:col-span-3">
            {TAB_CONFIG[effectiveTab].emptyMessage}
          </div>
        ) : (
          displayedTiles.map((tile) => (
            <TileCard
              key={tile.id}
              tile={tile}
              branchId={activeBranch?.id}
              isSelected={
                effectiveTab === 'stays'
                  ? selectedTiles?.stay?.id === tile.id
                  : effectiveTab === 'flights'
                    ? selectedTiles?.flight?.id === tile.id
                    : (selectedTiles?.activities.some(
                        (activity) => activity.id === tile.id
                      ) ?? false)
              }
              onToggleSelect={() => onTileToggle?.(tile, effectiveTab)}
              onSelectionToast={onSelectionToast}
              isSaved={savedTileIds.has(tile.id)}
              onOpenStaysSettings={effectiveTab === 'stays' ? onOpenStaysSettings : undefined}
            />
          ))
        )}
      </div>

      {/* Progressive disclosure: View All / Show Less buttons */}
      {hiddenCount > 0 && !isExpanded && (
        <button
          type="button"
          onClick={() => setIsExpanded(true)}
          className="w-full mt-2 py-3 rounded-xl text-sm font-medium border border-zinc-200 dark:border-white/10 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors flex items-center justify-center gap-2"
        >
          View All {filteredTiles.length} {TAB_CONFIG[effectiveTab].label}
          <ChevronDown className="w-4 h-4" />
        </button>
      )}

      {isExpanded && filteredTiles.length > DEFAULT_SHOW_COUNT && (
        <button
          type="button"
          onClick={() => setIsExpanded(false)}
          className="w-full mt-2 py-2 text-sm text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 transition-colors"
        >
          Show Less
        </button>
      )}
    </div>
  );
});
