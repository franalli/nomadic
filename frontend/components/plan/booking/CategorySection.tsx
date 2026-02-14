'use client';

import { ChevronDown, ChevronUp } from 'lucide-react';
import { memo, useCallback, useState } from 'react';

import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

/**
 * Tile thumbnail with fallback support.
 * Shows placeholder when image_url is missing or fails to load.
 */
const TileThumbnail = memo(function TileThumbnail({ tile }: { tile: Tile }) {
  const [hasError, setHasError] = useState(false);

  const handleError = useCallback(() => {
    setHasError(true);
  }, []);

  const imageSrc = hasError
    ? placeholderImageForTile(tile)
    : (tile.image_url || placeholderImageForTile(tile));

  return (
    <div className="flex-shrink-0 w-20 h-20 rounded-lg overflow-hidden bg-muted">
      <img
        src={imageSrc}
        alt={tile.title}
        className="w-full h-full object-cover"
        onError={handleError}
      />
    </div>
  );
});

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
  /** Current mode - determines UI variant (hearts vs cart) */
  mode?: 'planning' | 'booking';
}

/**
 * Traffic light status badge for booking status.
 * Mode-aware: Planning shows preference status, Booking shows cart status.
 */
function StatusBadge({ status, mode }: { status: 'available' | 'hold' | 'booked'; mode: 'planning' | 'booking' }) {
  // Planning mode: Show preference status
  if (mode === 'planning') {
    if (status === 'hold') {
      return (
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide text-emerald-500">
          <span className="text-sm">❤️</span>
          Preferred
        </div>
      );
    }
    // Don't show badge for non-preferred items in planning mode
    return null;
  }

  // Booking mode: Show cart status
  const config = {
    available: {
      dot: 'bg-zinc-400 dark:bg-zinc-500',
      text: 'text-zinc-500 dark:text-zinc-400',
      label: 'Available',
    },
    hold: {
      dot: 'bg-zinc-600 dark:bg-zinc-300',
      text: 'text-zinc-700 dark:text-zinc-300',
      label: 'In Cart',
    },
    booked: {
      dot: 'bg-emerald-500',
      text: 'text-emerald-600 dark:text-emerald-500',
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
  mode = 'booking',
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
                {/* Status badge - mode-aware */}
                <div className="absolute top-3 right-3 z-10">
                  <StatusBadge status={status} mode={mode} />
                </div>

                {/* Tile content */}
                <div className="flex gap-4">
                  {/* Thumbnail with fallback */}
                  <TileThumbnail tile={tile} />

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
                        <span className="text-emerald-500">★</span>
                        <span className="font-medium">{tile.rating.toFixed(1)}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Action button - mode-aware */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSaveTile?.(tile);
                  }}
                  className={cn(
                    'mt-3 w-full py-2 rounded-lg text-sm font-medium transition-colors',
                    isSaved
                      ? 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/30'
                      : 'bg-muted hover:bg-muted/80 text-foreground'
                  )}
                >
                  {mode === 'planning'
                    ? (isSaved ? 'Preferred ❤️' : 'Add to Trip ♡')
                    : (isSaved ? 'Remove from Cart' : 'Add to Cart')}
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
