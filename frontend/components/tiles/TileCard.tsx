import { Heart, MapPin, Star } from 'lucide-react';
import { type KeyboardEvent, type MouseEvent, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { getOrCreateSessionId } from '@/lib/session';
import type { Tile } from '@/types/tile';

type TileCardProps = {
  tile: Tile;
  branchId?: string;
  isSelected?: boolean;
  onToggleSelect?: (tile: Tile) => void;
};

const HOTEL_FEATURE_SETS = [
  ['Free WiFi', 'Breakfast Included', 'Rooftop Bar'],
  ['Pool', 'Spa', 'Restaurant'],
  ['Historic Building', 'City Views', 'Concierge'],
  ['Gym', 'Room Service', 'Bar'],
];

const FLIGHT_FEATURE_SETS = [
  ['Carry-on included', 'Meal included', 'USB Power'],
  ['Free cancellation', 'Seat selection', 'Wifi on board'],
  ['Priority boarding', 'Extra legroom', 'Lounge access'],
];

const ACTIVITY_FEATURE_SETS = [
  ['Small group', 'Guide included', 'Skip the line'],
  ['Private tour', 'Hotel pickup', 'Mobile ticket'],
  ['Instant confirmation', 'Free cancellation', 'English guide'],
];

const getFeaturesForTile = (tile: Tile): string[] => {
  const type = (tile.type || '').toLowerCase();
  let sets = HOTEL_FEATURE_SETS;

  if (['flight', 'air', 'fare', 'plane'].some((t) => type.includes(t))) {
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
  } else if (
    ['activity', 'experience', 'tour', 'excursion'].some((t) => type.includes(t))
  ) {
    sets = ACTIVITY_FEATURE_SETS;
    const meta = tile.meta as Record<string, unknown> | undefined;
    if (meta && typeof meta.duration === 'string') {
      // If we have duration, maybe use it as a feature or just stick to the sets
      // The design shows tags like "Pool", "Spa". Duration is usually in subtitle.
    }
  }

  // Deterministic selection based on tile ID
  const hash = tile.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return sets[hash % sets.length];
};

export function TileCard({
  tile,
  branchId,
  isSelected,
  onToggleSelect,
}: TileCardProps) {
  const [isLiked, setIsLiked] = useState(false);

  const features = useMemo(() => getFeaturesForTile(tile), [tile]);

  const handleClick = () => {
    const sessionId = getOrCreateSessionId();

    // Fire-and-forget click tracking
    apiFetch('/v1/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tile_id: tile.id,
        branch_id: branchId ?? null,
        session_id: sessionId,
        user_id: null,
      }),
    }).catch(() => {});

    // 3. Open partner deeplink immediately
    window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
  };

  const handleToggleSelect = (event: MouseEvent | KeyboardEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onToggleSelect?.(tile);
  };

  return (
    <Card
      onClick={handleToggleSelect}
      className={`bg-card group relative flex h-full flex-col overflow-hidden rounded-2xl border shadow-sm transition-all hover:shadow-md ${
        isSelected ? 'ring-primary border-primary ring-2' : 'border-border'
      }`}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          handleToggleSelect(event);
        }
      }}
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
          className="text-muted-foreground absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/90 shadow-sm transition hover:bg-white hover:text-red-500"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            setIsLiked((prev) => !prev);
          }}
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
            onClick={(event) => {
              event.stopPropagation();
              handleClick();
            }}
          >
            View Details
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
