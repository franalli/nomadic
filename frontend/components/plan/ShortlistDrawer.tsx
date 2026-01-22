/**
 * ShortlistDrawer
 *
 * Compact drawer showing saved/shortlisted items.
 * Opens via "Shortlist (n)" pill in DiscoverySection.
 *
 * Uses BaseSheet for responsive behavior:
 * - Desktop: Dialog
 * - Mobile: Bottom sheet
 */

'use client';

import { Heart, Star, Trash2 } from 'lucide-react';
import { memo, useMemo } from 'react';

import { BaseSheet } from '@/components/planner/sheets/BaseSheet';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';
import type { ShortlistCategory, ShortlistItem } from '@/hooks/useShortlist';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ShortlistDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: ShortlistItem[];
  tiles: Record<string, Tile>;
  primaryStayId: string | null;
  onRemove: (tileId: string) => void;
  onSetPrimary: (tileId: string) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function formatPrice(tile: Tile): string {
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

// ─────────────────────────────────────────────────────────────────────────────
// Item Row Component
// ─────────────────────────────────────────────────────────────────────────────

interface ItemRowProps {
  item: ShortlistItem;
  tile: Tile;
  isPrimary: boolean;
  onRemove: () => void;
  onSetPrimary: () => void;
}

const ItemRow = memo(function ItemRow({
  item,
  tile,
  isPrimary,
  onRemove,
  onSetPrimary,
}: ItemRowProps) {
  const price = formatPrice(tile);

  return (
    <div className="flex items-center gap-3 rounded-lg bg-zinc-800/50 p-2.5">
      {/* Thumbnail */}
      <div className="h-12 w-12 flex-shrink-0 overflow-hidden rounded-md bg-zinc-700">
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
        <div className="flex items-center gap-1.5">
          {isPrimary && (
            <Star className="h-3.5 w-3.5 flex-shrink-0 fill-amber-400 text-amber-400" />
          )}
          <span className="truncate text-sm font-medium text-zinc-200">
            {tile.title}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          {tile.location_label && <span>{tile.location_label}</span>}
          {price && tile.location_label && <span>·</span>}
          {price && <span className="text-zinc-400">{price}</span>}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1">
        {/* Set as primary (for stays only, if not already primary) */}
        {item.category === 'stays' && !isPrimary && (
          <button
            type="button"
            onClick={onSetPrimary}
            className="rounded p-1.5 text-zinc-500 transition-colors hover:bg-zinc-700 hover:text-amber-400"
            title="Set as primary stay"
          >
            <Star className="h-4 w-4" />
          </button>
        )}
        {/* Remove */}
        <button
          type="button"
          onClick={onRemove}
          className="rounded p-1.5 text-zinc-500 transition-colors hover:bg-zinc-700 hover:text-red-400"
          title="Remove from shortlist"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Category Section Component
// ─────────────────────────────────────────────────────────────────────────────

interface CategorySectionProps {
  label: string;
  items: ShortlistItem[];
  tiles: Record<string, Tile>;
  primaryStayId: string | null;
  onRemove: (tileId: string) => void;
  onSetPrimary: (tileId: string) => void;
}

const CategorySection = memo(function CategorySection({
  label,
  items,
  tiles,
  primaryStayId,
  onRemove,
  onSetPrimary,
}: CategorySectionProps) {
  if (items.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label} ({items.length})
      </h3>
      <div className="space-y-1.5">
        {items.map((item) => {
          const tile = tiles[item.tileId];
          if (!tile) return null;
          return (
            <ItemRow
              key={item.tileId}
              item={item}
              tile={tile}
              isPrimary={item.tileId === primaryStayId}
              onRemove={() => onRemove(item.tileId)}
              onSetPrimary={() => onSetPrimary(item.tileId)}
            />
          );
        })}
      </div>
    </div>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

export const ShortlistDrawer = memo(function ShortlistDrawer({
  open,
  onOpenChange,
  items,
  tiles,
  primaryStayId,
  onRemove,
  onSetPrimary,
}: ShortlistDrawerProps) {
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

  const isEmpty = items.length === 0;

  return (
    <BaseSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Your Shortlist"
      hint={isEmpty ? 'Save options to build your shortlist' : `${items.length} items saved`}
      footer={
        !isEmpty && (
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-500">
              {grouped.stays.length > 0 && !primaryStayId && (
                <span className="text-amber-500">
                  Tap the star to set your primary stay
                </span>
              )}
            </p>
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium',
                'bg-amber-500 text-white hover:bg-amber-600',
                'transition-colors'
              )}
            >
              Done
            </button>
          </div>
        )
      }
    >
      {isEmpty ? (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <Heart className="h-12 w-12 text-zinc-700 mb-3" />
          <p className="text-sm text-zinc-400">No items saved yet</p>
          <p className="mt-1 text-xs text-zinc-600">
            Tap the heart icon on any option to save it here
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          <CategorySection
            label="Stays"
            items={grouped.stays}
            tiles={tiles}
            primaryStayId={primaryStayId}
            onRemove={onRemove}
            onSetPrimary={onSetPrimary}
          />
          <CategorySection
            label="Flights"
            items={grouped.flights}
            tiles={tiles}
            primaryStayId={null}
            onRemove={onRemove}
            onSetPrimary={() => {}}
          />
          <CategorySection
            label="Activities"
            items={grouped.activities}
            tiles={tiles}
            primaryStayId={null}
            onRemove={onRemove}
            onSetPrimary={() => {}}
          />
        </div>
      )}
    </BaseSheet>
  );
});

export default ShortlistDrawer;
