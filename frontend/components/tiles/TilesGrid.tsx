'use client';

import { MapPin, Sparkles } from 'lucide-react';

import { TileCard } from '@/components/tiles/TileCard';
import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

type TilesGridProps = {
  tiles: Tile[];
  activeBranch?: PlanBranch | null;
  tilesRequestId?: string | null;
};

export function TilesGrid({ tiles, activeBranch, tilesRequestId }: TilesGridProps) {
  if (!tiles.length) {
    return (
      <div className="rounded-xl border border-dashed border-accent/30 bg-accent/5 p-4 text-sm text-muted-foreground shadow-inner">
        Booking options will appear after you request a plan.
      </div>
    );
  }

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

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {tiles.map((tile) => (
          <TileCard
            key={tile.id}
            tile={tile}
            branchId={activeBranch?.id}
            requestId={tilesRequestId ?? undefined}
          />
        ))}
      </div>
    </div>
  );
}
