'use client';

import { useEffect, useMemo, useState, type ElementType } from 'react';

import { MapPin, Plane, Sparkles, TentTree } from 'lucide-react';

import { TileCard } from '@/components/tiles/TileCard';
import type { PlanBranch } from '@/types/plan';
import type { Tile, TileSelection } from '@/types/tile';

export type TileTabKey = 'stays' | 'flights' | 'activities';

const TAB_CONFIG: Record<
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

const resolveTabForTile = (tile: Tile): TileTabKey => {
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
  tilesRequestId?: string | null;
  onTabChange?: (tab: TileTabKey, filteredTiles: Tile[]) => void;
  selectedTiles?: TileSelection;
  onTileToggle?: (tile: Tile, tab: TileTabKey) => void;
};

export function TilesGrid({
  tiles,
  activeBranch,
  tilesRequestId,
  onTabChange,
  selectedTiles,
  onTileToggle,
}: TilesGridProps) {
  const [activeTab, setActiveTab] = useState<TileTabKey>('stays');

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
    return tiles.filter((tile) => resolveTabForTile(tile) === activeTab);
  }, [activeTab, tiles]);

  useEffect(() => {
    onTabChange?.(activeTab, filteredTiles);
  }, [activeTab, filteredTiles, onTabChange]);

  return (
    <div className="flex flex-col gap-4">
      {activeBranch && (
        <div className="relative overflow-hidden rounded-xl border border-primary/30 bg-gradient-to-r from-primary/10 via-card/80 to-background p-4 text-xs shadow-md backdrop-blur">
          <div className="pointer-events-none absolute -right-14 -top-12 h-28 w-28 rounded-full bg-primary/20 blur-3xl" />
          <div className="relative flex flex-wrap items-center gap-3 text-foreground">
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-primary">
              <Sparkles className="h-3 w-3" />
              Live tiles
            </span>
            <div className="flex items-center gap-2 text-sm font-semibold">
              <MapPin className="h-4 w-4 text-primary" />
              {activeBranch.label} — {activeBranch.destination}
            </div>
            <span className="text-muted-foreground text-xs">
              Curated from your chat conversation.
            </span>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/30 p-2">
        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(TAB_CONFIG) as TileTabKey[]).map((tab) => {
            const Icon = TAB_CONFIG[tab].icon;
            const isActive = tab === activeTab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
                  isActive
                    ? 'bg-card shadow-sm shadow-primary/10 text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Icon className="h-4 w-4" />
                {TAB_CONFIG[tab].label}
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'bg-border/60 text-muted-foreground'
                  }`}
                >
                  {tabCounts[tab]}
                </span>
              </button>
            );
          })}
        </div>
        <div className="text-muted-foreground text-[11px] font-semibold uppercase tracking-wide">
          Tabs sync with the branch summary
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {filteredTiles.length === 0 ? (
          <div className="rounded-xl border border-dashed border-accent/30 bg-accent/5 p-4 text-sm text-muted-foreground shadow-inner md:col-span-2">
            {TAB_CONFIG[activeTab].emptyMessage}
          </div>
        ) : (
          filteredTiles.map((tile) => (
            <TileCard
              key={tile.id}
              tile={tile}
              branchId={activeBranch?.id}
              requestId={tilesRequestId ?? undefined}
              isSelected={
                activeTab === 'stays'
                  ? selectedTiles?.stay?.id === tile.id
                  : activeTab === 'flights'
                    ? selectedTiles?.flight?.id === tile.id
                    : selectedTiles?.activities.some((activity) => activity.id === tile.id) ??
                      false
              }
              onToggleSelect={() => onTileToggle?.(tile, activeTab)}
            />
          ))
        )}
      </div>
    </div>
  );
}
