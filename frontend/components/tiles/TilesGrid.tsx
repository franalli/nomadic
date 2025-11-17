'use client';

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
      <p className="text-sm text-slate-500">
        Tiles will appear after you request a plan.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {activeBranch && (
        <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
          Showing live options for{' '}
          <span className="font-semibold text-slate-800">{activeBranch.label}</span> (
          {activeBranch.destination}).
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
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
