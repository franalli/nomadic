'use client';

import { Plane, Sparkles, TentTree } from 'lucide-react';
import { type ElementType, useEffect, useMemo, useState } from 'react';

import { TileCard } from '@/components/tiles/TileCard';
import type { PlanBranch } from '@/types/plan';
import type { Tile, TileSelection } from '@/types/tile';

export type TileTabKey = 'stays' | 'flights' | 'activities';

export const TAB_CONFIG: Record<
  TileTabKey,
  { label: string; icon: ElementType; emptyMessage: string }
> = {
  stays: {
    label: 'Stays',
    icon: TentTree,
    emptyMessage: 'No stays yet for this suggestion — try refining dates or destination.',
  },
  flights: {
    label: 'Flights',
    icon: Plane,
    emptyMessage: 'No flights surfaced yet. Adjust the plan or try again in a moment.',
  },
  activities: {
    label: 'Activities',
    icon: Sparkles,
    emptyMessage: 'Activities will appear once we find matches for this plan.',
  },
};

export const resolveTabForTile = (tile: Tile): TileTabKey => {
  const type = (tile.type || '').toLowerCase();
  if (['flight', 'air', 'fare', 'plane'].some((needle) => type.includes(needle))) {
    return 'flights';
  }
  if (
    ['activity', 'experience', 'tour', 'excursion', 'ticket', 'event'].some((needle) =>
      type.includes(needle)
    )
  ) {
    return 'activities';
  }
  return 'stays';
};

type TilesGridProps = {
  tiles: Tile[];
  activeBranch?: PlanBranch | null;
  onTabChange?: (tab: TileTabKey, filteredTiles: Tile[]) => void;
  selectedTiles?: TileSelection;
  onTileToggle?: (tile: Tile, tab: TileTabKey) => void;
  forcedTab?: TileTabKey;
  hideTabSwitcher?: boolean;
};

export function TilesGrid({
  tiles,
  activeBranch,
  onTabChange,
  selectedTiles,
  onTileToggle,
  forcedTab,
  hideTabSwitcher = false,
}: TilesGridProps) {
  const [activeTab, setActiveTab] = useState<TileTabKey>(forcedTab ?? 'stays');
  const effectiveTab = forcedTab ?? activeTab;

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
    return tiles.filter((tile) => resolveTabForTile(tile) === effectiveTab);
  }, [effectiveTab, tiles]);

  useEffect(() => {
    onTabChange?.(effectiveTab, filteredTiles);
  }, [effectiveTab, filteredTiles, onTabChange]);

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
                        : 'border-border/70 text-muted-foreground bg-white'
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
        {filteredTiles.length === 0 ? (
          <div className="border-accent/30 bg-accent/5 text-muted-foreground rounded-xl border border-dashed p-4 text-sm shadow-inner sm:col-span-2 xl:col-span-3">
            {TAB_CONFIG[effectiveTab].emptyMessage}
          </div>
        ) : (
          filteredTiles.map((tile) => (
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
            />
          ))
        )}
      </div>
    </div>
  );
}
