import { Heart, MapPin, Star } from 'lucide-react';
import { type KeyboardEvent, memo, type MouseEvent, useCallback, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import {
  ACTIVITY_FEATURE_SETS,
  FLIGHT_FEATURE_SETS,
  HOTEL_FEATURE_SETS,
} from '@/lib/mocks';
import { isActivityType, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

type TileCardProps = {
  tile: Tile;
  branchId?: string;
  isSelected?: boolean;
  onToggleSelect?: (tile: Tile) => void;
};

const getFeaturesForTile = (tile: Tile): string[] => {
  const type = tile.type || '';
  let sets = HOTEL_FEATURE_SETS;

  if (isFlightType(type)) {
    sets = FLIGHT_FEATURE_SETS;
    // Try to use real meta if available
    const meta = tile.meta as Record<string, unknown> | undefined;
    if (meta) {
      const realFeatures: string[] = [];
      if (typeof meta.stops === 'string') realFeatures.push(meta.stops);
      if (typeof meta.fare_class === 'string') realFeatures.push(meta.fare_class);
      if (realFeatures.length > 0) {
        // Fill the rest with random features from the first set to make it look full
        while (realFeatures.length < 3) {
          const next = FLIGHT_FEATURE_SETS[0][realFeatures.length];
          if (!realFeatures.includes(next)) realFeatures.push(next);
        }
        return realFeatures;
      }
    }
  } else if (isActivityType(type)) {
    sets = ACTIVITY_FEATURE_SETS;
  }

  // Deterministic selection based on tile ID
  const hash = tile.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return sets[hash % sets.length];
};

export const TileCard = memo(function TileCard({
  tile,
  branchId,
  isSelected,
  onToggleSelect,
}: TileCardProps) {
  const [isLiked, setIsLiked] = useState(false);

  const features = useMemo(() => getFeaturesForTile(tile), [tile]);

  // Memoize click tracking payload to avoid recreating on each render
  const trackClick = useCallback(() => {
    apiFetch('/v1/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tile_id: tile.id,
        branch_id: branchId ?? null,
        user_id: null,
      }),
    }).catch((error) => {
      if (process.env.NODE_ENV !== 'production') {
        console.warn('Click tracking failed:', error);
      }
    });
  }, [tile.id, branchId]);

  const handleClick = useCallback(() => {
    // Fire-and-forget click tracking (session is sent via cookie)
    trackClick();
    // Open partner deeplink immediately
    window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
  }, [trackClick, tile.deeplink_url]);

  const handleToggleSelect = useCallback(
    (event: MouseEvent | KeyboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();
      onToggleSelect?.(tile);
    },
    [onToggleSelect, tile]
  );

  const handleLikeToggle = useCallback((event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    setIsLiked((prev) => !prev);
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        handleToggleSelect(event);
      }
    },
    [handleToggleSelect]
  );

  const handleViewDetailsClick = useCallback(
    (event: MouseEvent) => {
      event.stopPropagation();
      handleClick();
    },
    [handleClick]
  );

  return (
    <Card
      onClick={handleToggleSelect}
      className={`bg-card group relative flex h-full flex-col overflow-hidden rounded-2xl border shadow-sm transition-all hover:shadow-md ${
        isSelected ? 'ring-primary border-primary ring-2' : 'border-border'
      }`}
      role="button"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden">
        {tile.image_url ? (
          <img
            src={tile.image_url}
            alt={tile.title}
            className="h-full w-full object-cover transition duration-700 group-hover:scale-105"
          />
        ) : (
          <div className="from-primary/15 via-card to-background h-full w-full bg-gradient-to-br" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />

        <button
          type="button"
          className="text-muted-foreground absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-card/90 shadow-sm transition hover:bg-card hover:text-red-500"
          onClick={handleLikeToggle}
          aria-label={isLiked ? 'Unlike option' : 'Like option'}
        >
          <Heart className={`h-4 w-4 ${isLiked ? 'fill-red-500 text-red-500' : ''}`} />
        </button>
      </div>

      <CardBody className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="font-display text-foreground text-lg font-semibold leading-tight">
            {tile.title}
          </div>
          {tile.rating != null && (
            <div className="text-foreground flex shrink-0 items-center gap-1 text-sm font-medium">
              <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
              <span>{tile.rating.toFixed(1)}</span>
            </div>
          )}
        </div>

        {tile.location_label && (
          <div className="text-muted-foreground -mt-1 flex items-center gap-1.5 text-sm">
            <MapPin className="h-4 w-4 shrink-0" />
            <span className="line-clamp-1">{tile.location_label}</span>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {features.map((feature) => (
            <span
              key={feature}
              className="bg-muted text-muted-foreground inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium"
            >
              {feature}
            </span>
          ))}
        </div>

        <div className="mt-auto flex items-end justify-between pt-2">
          <div className="flex flex-col">
            <span className="text-muted-foreground text-xs">From</span>
            <div className="flex items-baseline gap-1">
              <span className="text-foreground text-lg font-bold">
                {tile.price_estimate != null ? `${tile.price_estimate}` : ''}
              </span>
              <span className="text-foreground text-sm font-medium">{tile.currency}</span>
              {tile.type?.toLowerCase().includes('stay') && (
                <span className="text-muted-foreground text-xs">/night</span>
              )}
            </div>
            {tile.price_estimate == null && (
              <span className="text-foreground text-sm font-bold">Check price</span>
            )}
          </div>
          <Button
            variant="primary"
            size="sm"
            className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold shadow-sm"
            onClick={handleViewDetailsClick}
          >
            View Details
          </Button>
        </div>
      </CardBody>
    </Card>
  );
});
