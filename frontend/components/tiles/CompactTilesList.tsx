/**
 * CompactTilesList
 *
 * Condensed row format for S2 preview. Shows tile name + price only.
 * Used in BookingSection collapsed preview state.
 */

'use client';

import type { Tile } from '@/types/tile';

export interface CompactTilesListProps {
  tiles: Tile[];
}

function formatPrice(
  amount: number | undefined,
  currency: string,
  priceBasis?: string
): string {
  if (amount == null || !currency) return '';
  const rounded = Math.round(amount).toLocaleString();
  const suffix =
    priceBasis === 'per_night' ? '/night' :
    priceBasis === 'per_person' ? '/person' :
    priceBasis === 'per_trip' ? '' : '';  // No suffix for total
  return `${currency} ${rounded}${suffix}`;
}

export function CompactTilesList({ tiles }: CompactTilesListProps) {
  if (tiles.length === 0) return null;

  return (
    <ul className="space-y-1">
      {tiles.map((tile) => (
        <li
          key={tile.id}
          className="flex items-center justify-between py-1.5 border-b border-zinc-800/50 last:border-0"
        >
          <span className="text-sm text-zinc-300 truncate max-w-[60%]">
            {tile.title}
          </span>
          <div className="flex items-center gap-2">
            {tile.rating && (
              <span className="text-xs text-zinc-500">
                {tile.rating.toFixed(1)}
              </span>
            )}
            <span className="text-sm text-zinc-400 font-medium">
              {formatPrice(tile.total_inclusive ?? tile.price_estimate, tile.currency, tile.price_basis)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export default CompactTilesList;
