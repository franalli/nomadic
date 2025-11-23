import type { KeyboardEvent, MouseEvent } from 'react';

import { ArrowUpRight, Star } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { apiFetch } from '@/lib/api';
import { getOrCreateSessionId } from '@/lib/session';
import type { Tile } from '@/types/tile';

type TileCardProps = {
  tile: Tile;
  requestId?: string;
  branchId?: string;
  isSelected?: boolean;
  onToggleSelect?: (tile: Tile) => void;
};

export function TileCard({ tile, requestId, branchId, isSelected, onToggleSelect }: TileCardProps) {
  const handleClick = () => {
    const sessionId = getOrCreateSessionId();

    // 2. Fire-and-forget click tracking
    const numericBranchId = branchId && /^\d+$/.test(branchId) ? Number(branchId) : null;

    apiFetch('/v1/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: requestId ?? null,
        tile_id: tile.id,
        branch_id: numericBranchId,
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
      className={`group relative flex h-full flex-col overflow-hidden border-none bg-card/80 shadow-lg ring-1 transition hover:-translate-y-0.5 hover:shadow-xl ${
        isSelected ? 'ring-2 ring-accent/70 shadow-accent/20' : 'ring-border/40'
      }`}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          handleToggleSelect(event);
        }
      }}
    >
      <div className="relative h-40 w-full overflow-hidden">
        {tile.image_url ? (
          <img
            src={tile.image_url}
            alt={tile.title}
            className="h-full w-full object-cover transition duration-700 group-hover:scale-105"
          />
        ) : (
          <div className="h-full w-full bg-gradient-to-br from-primary/15 via-card to-background" />
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/30 to-transparent" />
        <div className="absolute left-3 top-3 inline-flex items-center gap-1 rounded-full bg-black/50 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-white backdrop-blur">
          {tile.type}
        </div>
        {tile.rating != null && (
          <div className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-black/60 px-2 py-1 text-xs text-white backdrop-blur">
            <Star className="h-3 w-3 fill-accent text-accent" />
            {tile.rating.toFixed(1)}
          </div>
        )}
        {isSelected && (
          <div className="absolute right-3 bottom-3 rounded-full bg-black/60 px-2 py-1 text-xs font-semibold text-white backdrop-blur">
            Selected
          </div>
        )}
      </div>

      <CardBody className="relative flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-accent">
              Booking match
            </p>
            <div className="text-base font-display font-bold text-foreground">{tile.title}</div>
            {tile.subtitle && (
              <div className="text-sm text-muted-foreground">{tile.subtitle}</div>
            )}
            {tile.location_label && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                {tile.location_label}
              </div>
            )}
          </div>
          <div className="rounded-lg bg-primary/10 px-3 py-2 text-right">
            <div className="text-sm font-semibold text-primary">
              {tile.price_estimate != null
                ? `${tile.price_estimate} ${tile.currency}`
                : 'See price'}
            </div>
          </div>
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 pt-2">
          <span className="text-xs text-muted-foreground">Opens partner in a new tab</span>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1 text-primary hover:bg-primary/10"
            onClick={(event) => {
              event.stopPropagation();
              handleClick();
            }}
          >
            View
            <ArrowUpRight className="h-4 w-4" />
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
