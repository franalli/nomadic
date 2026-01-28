'use client';

import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

interface CategorySectionProps {
  /** Emoji for the category */
  emoji: string;
  /** Display label */
  label: string;
  /** Tiles in this category */
  items: Tile[];
  /** Set of saved tile IDs (for "In Trip" badge) */
  savedTileIds?: Set<string>;
  /** Callback when save button is clicked */
  onSaveTile?: (tile: Tile) => void;
  /** Callback when tile is clicked to view details */
  onTileClick?: (tile: Tile) => void;
  /** Initially expanded state */
  defaultExpanded?: boolean;
}

/**
 * Traffic light status badge for booking status.
 */
function StatusBadge({ status }: { status: 'available' | 'hold' | 'booked' }) {
  const config = {
    available: {
      dot: 'bg-gray-400',
      text: 'text-gray-500',
      label: 'Available',
    },
    hold: {
      dot: 'bg-amber-500',
      text: 'text-amber-500',
      label: 'In Cart',
    },
    booked: {
      dot: 'bg-emerald-500',
      text: 'text-emerald-500',
      label: 'Booked',
    },
  };

  const { dot, text, label } = config[status];

  return (
    <div className={cn('flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide', text)}>
      <span className={cn('w-2 h-2 rounded-full', dot)} />
      {label}
    </div>
  );
}

/**
 * CategorySection
 *
 * Collapsible category group for the Book view manifest.
 * Shows tiles grouped by category (Flights, Stays, Activities).
 */
export function CategorySection({
  emoji,
  label,
  items,
  savedTileIds = new Set(),
  onSaveTile,
  onTileClick,
  defaultExpanded = true,
}: CategorySectionProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  if (!items || items.length === 0) return null;

  return (
    <div className="bg-card border rounded-xl overflow-hidden shadow-sm transition-all hover:shadow-md">
      {/* Header */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 bg-muted/20 hover:bg-muted/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-2xl">{emoji}</span>
          <h3 className="font-semibold text-lg">{label}</h3>
          <span className="bg-muted px-2 py-0.5 rounded-full text-xs font-medium text-muted-foreground">
            {items.length} option{items.length !== 1 ? 's' : ''}
          </span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 text-muted-foreground" />
        ) : (
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        )}
      </button>

      {/* Tiles grid */}
      {isExpanded && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
          {items.map((tile) => {
            const isSaved = savedTileIds.has(tile.id);
            // Determine status based on saved state (simplified for MVP)
            const status: 'available' | 'hold' | 'booked' = isSaved ? 'hold' : 'available';

            return (
              <div
                key={tile.id}
                className="relative group rounded-xl border bg-background p-4 hover:border-primary/50 hover:shadow-md transition-all cursor-pointer"
                onClick={() => onTileClick?.(tile)}
              >
                {/* Status badge */}
                <div className="absolute top-3 right-3 z-10">
                  <StatusBadge status={status} />
                </div>

                {/* Tile content */}
                <div className="flex gap-4">
                  {/* Thumbnail */}
                  {tile.image_url && (
                    <div className="flex-shrink-0 w-20 h-20 rounded-lg overflow-hidden bg-muted">
                      <img
                        src={tile.image_url}
                        alt={tile.title}
                        className="w-full h-full object-cover"
                      />
                    </div>
                  )}

                  {/* Details */}
                  <div className="flex-1 min-w-0">
                    <h4 className="font-medium text-foreground truncate pr-16">
                      {tile.title}
                    </h4>
                    {tile.location_label && (
                      <p className="text-sm text-muted-foreground truncate mt-0.5">
                        {tile.location_label}
                      </p>
                    )}

                    {/* Price */}
                    <div className="mt-2 flex items-baseline gap-1">
                      <span className="text-lg font-bold">
                        {tile.currency === 'USD' ? '$' : tile.currency}
                        {(tile.total_inclusive ?? tile.price_estimate ?? 0).toLocaleString()}
                      </span>
                      {tile.price_basis && (
                        <span className="text-xs text-muted-foreground">
                          /{tile.price_basis === 'per_night' ? 'night' : tile.price_basis}
                        </span>
                      )}
                    </div>

                    {/* Rating */}
                    {tile.rating && (
                      <div className="mt-1 flex items-center gap-1 text-sm">
                        <span className="text-amber-500">★</span>
                        <span className="font-medium">{tile.rating.toFixed(1)}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Save button */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSaveTile?.(tile);
                  }}
                  className={cn(
                    'mt-3 w-full py-2 rounded-lg text-sm font-medium transition-colors',
                    isSaved
                      ? 'bg-amber-500/10 text-amber-600 border border-amber-500/30'
                      : 'bg-muted hover:bg-muted/80 text-foreground'
                  )}
                >
                  {isSaved ? 'Remove from Trip' : 'Add to Trip'}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default CategorySection;
