/**
 * ShortlistPanel
 *
 * Shows the user's saved/shortlisted tiles in S2.
 * Displays items by category with ability to remove or set primary.
 *
 * Note: CTA to proceed is in NextStepBar, not here.
 */

'use client';

import { Heart, Star, X } from 'lucide-react';
import { memo, useMemo } from 'react';

import type { Tile } from '@/types/tile';

import type { ShortlistCategory, ShortlistItem } from '@/hooks/useShortlist';

export interface ShortlistPanelProps {
  items: ShortlistItem[];
  tiles: Record<string, Tile>;
  primaryStayId: string | null;
  onRemove: (tileId: string) => void;
  onSetPrimary: (tileId: string) => void;
}

/**
 * Format price for shortlist item
 */
function formatShortPrice(tile: Tile): string {
  const price = tile.total_inclusive ?? tile.price_estimate;
  if (price == null) return '';

  const currency = tile.currency || 'USD';
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(price);

  const basis = tile.price_basis;
  if (basis === 'per_night') return `${formatted}/night`;
  if (basis === 'per_person') return `${formatted}/person`;
  return formatted;
}

/**
 * Single shortlist item row
 */
const ShortlistItemRow = memo(function ShortlistItemRow({
  item,
  tile,
  isPrimary,
  onRemove,
  onSetPrimary,
}: {
  item: ShortlistItem;
  tile: Tile;
  isPrimary: boolean;
  onRemove: () => void;
  onSetPrimary: () => void;
}) {
  const price = formatShortPrice(tile);

  return (
    <div className="flex items-center gap-2 rounded-lg bg-zinc-800/50 p-2">
      {/* Thumbnail */}
      <div className="h-10 w-10 flex-shrink-0 overflow-hidden rounded bg-zinc-700">
        {tile.image_url ? (
          <img
            src={tile.image_url}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <Heart className="h-4 w-4 text-zinc-500" />
          </div>
        )}
      </div>

      {/* Info */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1">
          {isPrimary && (
            <Star className="h-3 w-3 flex-shrink-0 fill-amber-400 text-amber-400" />
          )}
          <span className="truncate text-sm text-zinc-200">{tile.title}</span>
        </div>
        {price && <span className="text-xs text-zinc-500">{price}</span>}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1">
        {/* Set as primary (for stays only, if not already primary) */}
        {item.category === 'stays' && !isPrimary && (
          <button
            type="button"
            onClick={onSetPrimary}
            className="rounded p-1 text-zinc-500 transition-colors hover:bg-zinc-700 hover:text-amber-400"
            title="Set as primary stay"
          >
            <Star className="h-4 w-4" />
          </button>
        )}
        {/* Remove */}
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1 text-zinc-500 transition-colors hover:bg-zinc-700 hover:text-zinc-300"
          title="Remove from shortlist"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
});

export const ShortlistPanel = memo(function ShortlistPanel({
  items,
  tiles,
  primaryStayId,
  onRemove,
  onSetPrimary,
}: ShortlistPanelProps) {
  // Group items by category
  const grouped = useMemo(() => {
    const result: Record<ShortlistCategory, ShortlistItem[]> = {
      stays: [],
      flights: [],
      activities: [],
    };
    for (const item of items) {
      result[item.category].push(item);
    }
    return result;
  }, [items]);

  const totalCount = items.length;

  if (totalCount === 0) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
        <div className="flex items-center gap-2 text-zinc-500">
          <Heart className="h-4 w-4" />
          <span className="text-sm">No items saved yet</span>
        </div>
        <p className="mt-2 text-xs text-zinc-600">
          Save options from above to build your shortlist.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50">
      {/* Header */}
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-zinc-200">Your shortlist</h3>
          <span className="text-xs text-zinc-500">{totalCount} saved</span>
        </div>
        {/* Category counts */}
        <div className="mt-1.5 flex gap-3 text-xs text-zinc-500">
          {grouped.stays.length > 0 && (
            <span>Stays ({grouped.stays.length})</span>
          )}
          {grouped.flights.length > 0 && (
            <span>Flights ({grouped.flights.length})</span>
          )}
          {grouped.activities.length > 0 && (
            <span>Activities ({grouped.activities.length})</span>
          )}
        </div>
      </div>

      {/* Items list */}
      <div className="max-h-64 space-y-1.5 overflow-y-auto p-3">
        {/* Stays first (most important) */}
        {grouped.stays.map((item) => {
          const tile = tiles[item.tileId];
          if (!tile) return null;
          return (
            <ShortlistItemRow
              key={item.tileId}
              item={item}
              tile={tile}
              isPrimary={item.tileId === primaryStayId}
              onRemove={() => onRemove(item.tileId)}
              onSetPrimary={() => onSetPrimary(item.tileId)}
            />
          );
        })}
        {/* Flights */}
        {grouped.flights.map((item) => {
          const tile = tiles[item.tileId];
          if (!tile) return null;
          return (
            <ShortlistItemRow
              key={item.tileId}
              item={item}
              tile={tile}
              isPrimary={false}
              onRemove={() => onRemove(item.tileId)}
              onSetPrimary={() => {}}
            />
          );
        })}
        {/* Activities */}
        {grouped.activities.map((item) => {
          const tile = tiles[item.tileId];
          if (!tile) return null;
          return (
            <ShortlistItemRow
              key={item.tileId}
              item={item}
              tile={tile}
              isPrimary={false}
              onRemove={() => onRemove(item.tileId)}
              onSetPrimary={() => {}}
            />
          );
        })}
      </div>

      {/* Hint for primary stay */}
      {grouped.stays.length > 0 && !primaryStayId && (
        <div className="border-t border-zinc-800 px-4 py-2">
          <p className="text-xs text-amber-500/80">
            Tap the star to set your primary stay
          </p>
        </div>
      )}
    </div>
  );
});

export default ShortlistPanel;
