'use client';

import { Settings } from 'lucide-react';
import { useState } from 'react';

import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isFlightType, isHotelType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

type MiniCardSummaryThumbnailProps = {
  tile: Tile;
  onOpenStaysSettings?: () => void;
};

export function MiniCardSummaryThumbnail({
  tile,
  onOpenStaysSettings,
}: MiniCardSummaryThumbnailProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const isFlight = isFlightType(tile.type || '');

  return (
    <div
      className={cn(
        'relative flex-shrink-0 overflow-hidden',
        isFlight
          ? 'flex h-12 w-12 items-center justify-center rounded-full bg-white'
          : 'h-16 w-16 rounded-md bg-zinc-100 dark:bg-zinc-800'
      )}
    >
      <img
        src={imageError ? placeholderImageForTile(tile) : (tile.image_url || placeholderImageForTile(tile))}
        alt={tile.title}
        loading="lazy"
        onLoad={() => setImageLoaded(true)}
        onError={() => setImageError(true)}
        className={cn(
          'transition-opacity duration-300',
          isFlight ? 'h-10 w-10 object-contain' : 'h-full w-full object-cover',
          !imageLoaded && 'opacity-0'
        )}
      />
      {onOpenStaysSettings && isHotelType(tile.type || '') && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onOpenStaysSettings();
          }}
          className={cn(
            'absolute bottom-1 right-1 rounded bg-black/60 p-1 backdrop-blur-sm transition-colors hover:bg-black/80'
          )}
          aria-label="Hotel settings"
        >
          <Settings className="h-3 w-3 text-zinc-300" />
        </button>
      )}
    </div>
  );
}
