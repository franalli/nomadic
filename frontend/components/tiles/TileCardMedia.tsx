'use client';

import { Heart, Settings } from 'lucide-react';
import type { MouseEvent } from 'react';
import { useEffect, useMemo, useState } from 'react';

import {
  getSignedGooglePlacesPhotoProxyUrl,
  normalizeGooglePlacesPhotoName,
} from '@/lib/googlePlacesPhoto';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isHotelType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../ui/tooltip';

type TileCardMediaProps = {
  tile: Tile;
  isFlight: boolean;
  isPreferred: boolean;
  isSaved: boolean;
  heartAnimating: boolean;
  onPreferenceToggle: (event: MouseEvent<HTMLButtonElement>) => void;
  onOpenStaysSettings?: () => void;
};

export function TileCardMedia({
  tile,
  isFlight,
  isPreferred,
  isSaved,
  heartAnimating,
  onPreferenceToggle,
  onOpenStaysSettings,
}: TileCardMediaProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const photoName = useMemo(() => {
    const meta = tile.meta as Record<string, unknown> | undefined;
    return normalizeGooglePlacesPhotoName(meta?.photo_name);
  }, [tile]);
  const [signedPhotoUrl, setSignedPhotoUrl] = useState<string | undefined>(undefined);

  useEffect(() => {
    let isMounted = true;
    setSignedPhotoUrl(undefined);
    if (!photoName) return () => { isMounted = false; };

    getSignedGooglePlacesPhotoProxyUrl(photoName, { maxWidth: 320, maxHeight: 240 })
      .then((url) => {
        if (!isMounted) return;
        setSignedPhotoUrl(url);
      })
      .catch(() => {
        if (!isMounted) return;
        setSignedPhotoUrl(undefined);
      });

    return () => {
      isMounted = false;
    };
  }, [photoName]);

  const imageSrc = imageError
    ? placeholderImageForTile(tile)
    : (signedPhotoUrl || tile.image_url || placeholderImageForTile(tile));

  return (
    <div
      className={cn(
        'relative w-full overflow-hidden',
        isFlight
          ? 'aspect-[16/10] bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center'
          : 'aspect-[16/9]'
      )}
    >
      {!imageLoaded && !isFlight && (
        <div className="absolute inset-0 animate-pulse rounded-none bg-zinc-200/50 dark:bg-zinc-700/50" />
      )}
      {isFlight ? (
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-white shadow-sm">
          <img
            src={imageSrc}
            alt={tile.title}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={cn(
              'h-12 w-12 object-contain transition-opacity duration-300',
              !imageLoaded && 'opacity-0'
            )}
          />
        </div>
      ) : (
        <img
          src={imageSrc}
          alt={tile.title}
          loading="lazy"
          onLoad={() => setImageLoaded(true)}
          onError={() => setImageError(true)}
          className={cn(
            'h-full w-full object-cover transition duration-700 group-hover:scale-105',
            !imageLoaded && 'opacity-0'
          )}
        />
      )}
      {!isFlight && (
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />
      )}

      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className={cn(
                'absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full transition-all touch-manipulation',
                'bg-black/40 backdrop-blur-sm',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50',
                heartAnimating && 'scale-110'
              )}
              onClick={onPreferenceToggle}
              aria-label={isPreferred ? 'Remove from preferences' : 'Add to preferences'}
              aria-pressed={isPreferred}
            >
              <Heart
                className={cn(
                  'h-5 w-5 transition-colors',
                  isPreferred
                    ? 'fill-emerald-500 stroke-emerald-500'
                    : 'stroke-zinc-400 fill-transparent hover:stroke-zinc-300'
                )}
              />
            </button>
          </TooltipTrigger>
          <TooltipContent side="left" className="text-xs">
            {isPreferred ? 'Remove preference' : 'Prefer this option'}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      {onOpenStaysSettings && isHotelType(tile.type || '') && (
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={cn(
                  'absolute right-12 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full transition-all touch-manipulation',
                  'bg-black/40 backdrop-blur-sm hover:bg-black/60',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50'
                )}
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenStaysSettings();
                }}
                aria-label="Hotel settings"
              >
                <Settings className="h-4 w-4 text-zinc-300" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="left" className="text-xs">
              Hotel preferences
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}

      {isPreferred && (
        <div className="absolute left-2 top-2 flex items-center gap-1 rounded-full bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
          <Heart className="h-3 w-3 fill-white" />
          Preferred
        </div>
      )}
      {!isPreferred && isSaved && (
        <div className="absolute left-2 top-2 rounded bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
          Saved
        </div>
      )}
      {!isSaved && tile.is_refundable === false && (
        <div className="absolute left-2 top-2 rounded bg-zinc-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
          Non-refundable
        </div>
      )}
      {!isSaved && tile.is_refundable === true && (
        <div className="absolute left-2 top-2 rounded bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
          Free cancellation
        </div>
      )}
    </div>
  );
}
