'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * MiniCard
 *
 * Compact tile card for S2 (Plan) discovery view.
 * Shows enough info to evaluate: thumbnail, name, area, rating, price, perks.
 *
 * Interaction model:
 * - Click card → opens modal (full details)
 * - Click Save → saves to shortlist
 * - Click Quick facts → toggles inline expansion (independent per tile)
 */


import { memo, useCallback, useMemo } from 'react';

import { MiniCardContent } from '@/components/tiles/MiniCardContent';
import { Skeleton } from '@/components/ui/skeleton';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

interface MiniCardProps {
  tile: Tile;
  isSaved?: boolean;
  /** Callback when card is clicked (opens modal) */
  onDetailsClick?: (tile: Tile) => void;
  onSaveClick?: (tile: Tile) => void;
  /** Callback to open category-wide stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
  /** Override the default "Add to Trip" label on the save button */
  saveLabel?: string;
}

/**
 * MiniCardSkeleton - Shimmer placeholder during loading
 * Shows structure hint including logic hook placeholder
 */
export const MiniCardSkeleton = memo(function MiniCardSkeleton() {
  return (
    <div className="relative rounded-lg border border-zinc-200 dark:border-white/10 bg-white/95 dark:bg-white/5 shadow-card p-3">
      <div className="flex items-start gap-4">
        <Skeleton className="h-16 w-16 flex-shrink-0 rounded-md bg-zinc-200/50 dark:bg-zinc-700/50" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Skeleton className="h-4 w-3/4 bg-zinc-200/50 dark:bg-zinc-700/50" />
          <Skeleton className="h-3 w-1/2 bg-zinc-200/50 dark:bg-zinc-700/50" />
          <div className="flex gap-1.5">
            <Skeleton className="h-5 w-14 rounded bg-zinc-200/50 dark:bg-zinc-700/50" />
            <Skeleton className="h-5 w-16 rounded bg-zinc-200/50 dark:bg-zinc-700/50" />
          </div>
          <Skeleton className="h-5 w-20 mt-1 bg-zinc-200/50 dark:bg-zinc-700/50" />
          {/* Logic hook hint - emerald tinted */}
          <Skeleton className="h-6 w-full rounded-md bg-emerald-100/50 dark:bg-emerald-900/10 mt-1" />
        </div>
      </div>
    </div>
  );
});

/**
 * Extract perk chips from tile (max 3)
 */
function getPerks(tile: Tile): string[] {
  const perks: string[] = [];

  if (tile.is_refundable === true) {
    perks.push('Free cancel');
  }

  const meta = tile.meta as Record<string, unknown> | undefined;
  if (meta?.features && Array.isArray(meta.features)) {
    const features = meta.features as string[];
    perks.push(...features.slice(0, 2));
  }

  if (isFlightType(tile.type || '')) {
    if (typeof meta?.stops === 'string') perks.push(meta.stops);
    if (typeof meta?.fare_class === 'string') perks.push(meta.fare_class);
  }

  return perks.slice(0, 3);
}

export const MiniCard = memo(function MiniCard({
  tile,
  isSaved = false,
  onDetailsClick,
  onSaveClick,
  onOpenStaysSettings,
  saveLabel,
}: MiniCardProps) {
  const perks = useMemo(() => getPerks(tile), [tile]);

  // Safety Shield Logic - for flight cards with diving constraints
  const meta = tile.meta as Record<string, unknown> | undefined;
  const isUnsafe = isFlightType(tile.type || '') && meta?.is_safe === false;

  // Card click -> opens modal
  const handleCardClick = useCallback(() => {
    onDetailsClick?.(tile);
  }, [onDetailsClick, tile]);

  // Save button - stopPropagation to prevent modal open
  const handleSaveClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onSaveClick?.(tile);
    },
    [onSaveClick, tile]
  );

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleCardClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleCardClick();
        }
      }}
      className={cn(
        'relative rounded-lg border transition-all cursor-pointer',
        // Safety Shield: Zinc border for unsafe flights (warning)
        isUnsafe
          ? 'border-zinc-500/50 bg-zinc-950/10'
          : [
              // Light: Tactile Rule - white glass with visible border and shadow
              'bg-white/95 border-zinc-200 shadow-card',
              'hover:border-zinc-300 hover:shadow-soft hover:translate-y-[-1px]',
              // Dark: Glass fill with subtle border
              'dark:bg-white/5 dark:border-white/10',
              'dark:hover:bg-white/10 dark:hover:border-white/20',
            ],
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40 focus-visible:ring-offset-2',
      )}
    >
      <MiniCardContent
        tile={tile}
        isSaved={isSaved}
        perks={perks}
        onSaveClick={handleSaveClick}
        onOpenStaysSettings={onOpenStaysSettings}
        saveLabel={saveLabel}
      />
    </div>
  );
});

export default MiniCard;
