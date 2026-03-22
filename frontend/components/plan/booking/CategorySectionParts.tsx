'use client';

/**
 * CategorySectionParts — Extracted sub-components for CategorySection.
 */

import { memo, useCallback, useState } from 'react';

import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

/**
 * Tile thumbnail with fallback support.
 * Shows placeholder when image_url is missing or fails to load.
 */
export const TileThumbnail = memo(function TileThumbnail({ tile }: { tile: Tile }) {
  const [hasError, setHasError] = useState(false);

  const handleError = useCallback(() => {
    setHasError(true);
  }, []);

  const imageSrc = hasError
    ? placeholderImageForTile(tile)
    : (tile.image_url || placeholderImageForTile(tile));

  return (
    <div className="flex-shrink-0 w-20 h-20 rounded-lg overflow-hidden bg-zinc-100 dark:bg-zinc-800">
      <img
        src={imageSrc}
        alt={tile.title}
        loading="lazy"
        className="w-full h-full object-cover"
        onError={handleError}
      />
    </div>
  );
});

/**
 * Traffic light status badge for booking status.
 * Mode-aware: Planning shows preference status, Booking shows cart status.
 */
export function StatusBadge({ status, mode }: { status: 'available' | 'hold' | 'booked'; mode: 'planning' | 'booking' }) {
  // Planning mode: Show preference status
  if (mode === 'planning') {
    if (status === 'hold') {
      return (
        <div className={`flex items-center gap-1.5 ${DS.textSize.micro} font-bold uppercase tracking-wide text-emerald-500`}>
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
    <div className={cn(`flex items-center gap-1.5 ${DS.textSize.micro} font-bold uppercase tracking-wide`, text)}>
      <span className={cn('w-2 h-2 rounded-full', dot)} />
      {label}
    </div>
  );
}
