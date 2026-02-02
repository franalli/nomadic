/**
 * BookingDrawer
 *
 * Side sheet marketplace for selecting hotels, flights, or activities.
 * Uses glass aesthetic and shows tiles filtered by category.
 *
 * @see docs/ux_unified_architecture.md Section 10.E
 */

'use client';

import { Package, X } from 'lucide-react';

import { MiniCard } from '@/components/tiles/MiniCard';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { normalizeTileType } from '@/lib/tileSelectors';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

export interface BookingDrawerProps {
  /** Category to filter tiles by */
  category: 'hotel' | 'flight' | 'activity' | null;
  /** All available tiles */
  tiles?: Record<string, Tile>;
  /** Set of saved tile IDs */
  savedTileIds?: Set<string>;
  /** Callback when user saves a tile */
  onSave?: (tile: Tile) => void;
  /** Callback when drawer is closed */
  onClose: () => void;
  /** Callback to open stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
}

const CATEGORY_LABELS = {
  hotel: 'Select Your Stay',
  flight: 'Select Your Flight',
  activity: 'Browse Activities',
} as const;

/**
 * Filter tiles by category using normalized type matching.
 * Handles case variations, compound types, and synonyms.
 */
function filterTilesByCategory(tiles: Record<string, Tile>, category: 'hotel' | 'flight' | 'activity'): Tile[] {
  const all = Object.values(tiles);
  const filtered = all.filter((tile) => normalizeTileType(tile.type) === category);

  // DEBUG: Log tile type distribution to help diagnose "0 options" issue
  if (process.env.NODE_ENV === 'development') {
    console.log(`[BookingDrawer] Category: ${category}, Total tiles: ${all.length}, Matched: ${filtered.length}`);
    if (filtered.length === 0 && all.length > 0) {
      console.log('[BookingDrawer] All types:', all.map(t => `${t.id}: "${t.type}"`));
    }
  }

  return filtered;
}

export function BookingDrawer({
  category,
  tiles = {},
  savedTileIds = new Set(),
  onSave,
  onClose,
  onOpenStaysSettings,
}: BookingDrawerProps) {
  if (!category) return null;

  const categoryTiles = filterTilesByCategory(tiles, category);

  return (
    <Sheet open={!!category} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className={cn(
          'w-full sm:w-[480px] p-0',
          // Glass aesthetic from design-system.md
          'bg-white/80 dark:bg-zinc-900/80',
          'backdrop-blur-xl',
          'border-l border-white/20 dark:border-white/10'
        )}
      >
        {/* Header */}
        <SheetHeader className="p-4 border-b border-border/50">
          <div className="flex items-center justify-between">
            <SheetTitle>{CATEGORY_LABELS[category]}</SheetTitle>
            <button
              onClick={onClose}
              className="p-2 hover:bg-muted rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <p className="text-sm text-muted-foreground">
            {categoryTiles.length} option{categoryTiles.length !== 1 ? 's' : ''} available
          </p>
        </SheetHeader>

        {/* Tile List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {categoryTiles.map((tile) => (
            <MiniCard
              key={tile.id}
              tile={tile}
              isSaved={savedTileIds.has(tile.id)}
              onSaveClick={(t) => {
                onSave?.(t);
                onClose();
              }}
              onOpenStaysSettings={category === 'hotel' ? onOpenStaysSettings : undefined}
            />
          ))}

          {/* Empty state */}
          {categoryTiles.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <Package className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p className="font-medium">No {category === 'activity' ? 'activities' : `${category}s`} available</p>
              <p className="text-sm mt-1 text-muted-foreground/70">
                {category === 'activity'
                  ? 'Activities will appear once specialists have generated recommendations.'
                  : 'Try adjusting your dates or destination.'}
              </p>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default BookingDrawer;
