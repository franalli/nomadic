/**
 * SelectionsBar
 *
 * Horizontal carousel showing tiles the user has hearted (preferred).
 * Provides live preview of selections before itinerary generation.
 * Becomes sticky after scroll threshold.
 *
 * @see docs/ux_unified_architecture.md - Unified Planning View
 */

'use client';

import { Heart, X } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

export interface SelectionsBarProps {
  /** Map of all tiles (keyed by ID) */
  tiles: Record<string, Tile>;
  /** Set of preferred tile IDs from documentStore */
  preferredTileIds: Set<string>;
  /** Callback when user removes a preference */
  onRemovePreference: (tileId: string) => void;
  /** Callback when user clicks on a tile (scroll to tile in browser) */
  onTileClick: (tileId: string) => void;
  /** Whether bar is in sticky mode */
  isSticky?: boolean;
  /** Additional className */
  className?: string;
}

export function SelectionsBar({
  tiles,
  preferredTileIds,
  onRemovePreference,
  onTileClick,
  isSticky = false,
  className,
}: SelectionsBarProps) {
  // Filter to get only preferred tiles that exist
  // Safety: handle case where tiles might be undefined or empty
  const preferredTiles = Array.from(preferredTileIds)
    .map((id) => tiles?.[id])
    .filter(Boolean);

  // Empty state - show hint to heart tiles
  if (preferredTiles.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground',
          'border-b border-border/50',
          className
        )}
      >
        <Heart className="h-4 w-4 text-zinc-500" />
        <span>Heart tiles below to build your trip</span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'px-4 py-3 border-b border-border/50 transition-all duration-200',
        isSticky && 'bg-background/95 backdrop-blur-sm shadow-lg',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Heart className="h-3.5 w-3.5 text-emerald-500 fill-emerald-500" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Your Selections
        </h3>
        <span className="text-xs px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">
          {preferredTiles.length}
        </span>
      </div>

      {/* Horizontal scroll carousel */}
      <div className="flex gap-3 overflow-x-auto snap-x snap-mandatory pb-1 -mx-1 px-1 scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
        {preferredTiles.map((tile) => (
          <div
            key={tile.id}
            role="button"
            tabIndex={0}
            onClick={() => onTileClick(tile.id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onTileClick(tile.id);
              }
            }}
            className="flex-shrink-0 snap-start group relative text-left cursor-pointer"
          >
            {/* Thumbnail */}
            <div className="w-24 h-16 rounded-lg overflow-hidden bg-zinc-800 ring-1 ring-white/10">
              {tile.image_url ? (
                <img
                  src={tile.image_url}
                  alt={tile.title}
                  className="w-full h-full object-cover transition-transform group-hover:scale-105"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-zinc-600">
                  <Heart className="h-5 w-5" />
                </div>
              )}
            </div>

            {/* Title */}
            <span className="block text-xs mt-1.5 truncate w-24 text-zinc-300 group-hover:text-white transition-colors">
              {tile.title}
            </span>

            {/* Price (if available) */}
            {tile.price_estimate && (
              <span className="block text-[10px] text-zinc-500">
                {tile.currency === 'USD' ? '$' : tile.currency}
                {tile.price_estimate.toLocaleString()}
              </span>
            )}

            {/* Remove button - shows on hover */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onRemovePreference(tile.id);
              }}
              className={cn(
                'absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full',
                'bg-zinc-800 border border-zinc-700 hover:bg-red-600 hover:border-red-600',
                'flex items-center justify-center',
                'opacity-0 group-hover:opacity-100 transition-all duration-150',
                'focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500'
              )}
              aria-label={`Remove ${tile.title} from selections`}
            >
              <X className="w-3 h-3 text-zinc-400 group-hover:text-white" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default SelectionsBar;
