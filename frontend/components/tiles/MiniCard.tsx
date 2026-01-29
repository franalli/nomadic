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

'use client';

import { ChevronDown, Code2, Heart, Star } from 'lucide-react';
import { memo, useCallback, useMemo, useState } from 'react';

import { Skeleton } from '@/components/ui/skeleton';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { placeholderImageForTile } from '@/lib/placeholders';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

export interface MiniCardProps {
  tile: Tile;
  isSaved?: boolean;
  /** Callback when card is clicked (opens modal) */
  onDetailsClick?: (tile: Tile) => void;
  onSaveClick?: (tile: Tile) => void;
}

/**
 * MiniCardSkeleton - Shimmer placeholder during loading
 * Shows structure hint including logic hook placeholder
 */
export const MiniCardSkeleton = memo(function MiniCardSkeleton() {
  return (
    <div className="relative rounded-lg border border-border bg-card shadow-sm p-3">
      <div className="flex items-start gap-3">
        <Skeleton className="h-16 w-16 flex-shrink-0 rounded-md bg-muted/50" />
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Skeleton className="h-4 w-3/4 bg-muted/50" />
          <Skeleton className="h-3 w-1/2 bg-muted/50" />
          <div className="flex gap-1.5">
            <Skeleton className="h-5 w-14 rounded bg-muted/50" />
            <Skeleton className="h-5 w-16 rounded bg-muted/50" />
          </div>
          <Skeleton className="h-5 w-20 mt-1 bg-muted/50" />
          {/* Logic hook hint - emerald tinted */}
          <Skeleton className="h-6 w-full rounded-md bg-emerald-900/10 mt-1" />
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

  // Refundability
  if (tile.is_refundable === true) {
    perks.push('Free cancel');
  }

  // Features from meta
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (meta?.features && Array.isArray(meta.features)) {
    const features = meta.features as string[];
    // Add up to 2 more features (we already have refundability)
    perks.push(...features.slice(0, 2));
  }

  // For flights, add stops/class
  if (isFlightType(tile.type || '')) {
    if (typeof meta?.stops === 'string') perks.push(meta.stops);
    if (typeof meta?.fare_class === 'string') perks.push(meta.fare_class);
  }

  return perks.slice(0, 3);
}

/**
 * Format price with currency and basis
 */
function formatPrice(tile: Tile): string {
  const price = tile.total_inclusive ?? tile.price_estimate;
  if (price == null) return '';

  const currency = tile.currency || 'USD';
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(price);

  // Add basis suffix
  const basis = tile.price_basis;
  if (basis === 'per_night') return `${formatted} /night`;
  if (basis === 'per_person') return `${formatted} /person`;
  if (basis === 'total' || tile.total_inclusive != null) return `${formatted} total`;

  return formatted;
}

/**
 * Get amenities from tile meta (for inline expansion)
 */
function getAmenities(tile: Tile): string[] {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (meta?.amenities && Array.isArray(meta.amenities)) {
    return meta.amenities as string[];
  }
  if (meta?.features && Array.isArray(meta.features)) {
    return meta.features as string[];
  }
  return [];
}

/**
 * Get cancellation text (for inline expansion)
 */
function getCancellationText(tile: Tile): string | null {
  if (tile.is_refundable === true) {
    const meta = tile.meta as Record<string, unknown> | undefined;
    if (typeof meta?.cancellation_deadline === 'string') {
      return `Free cancellation until ${meta.cancellation_deadline}`;
    }
    return 'Free cancellation available';
  }
  if (tile.is_refundable === false) {
    return 'Non-refundable';
  }
  return null;
}

/**
 * Get check-in/out times (for inline expansion)
 */
function getCheckTimes(tile: Tile): { checkIn?: string; checkOut?: string } {
  const meta = tile.meta as Record<string, unknown> | undefined;
  return {
    checkIn: typeof meta?.check_in === 'string' ? meta.check_in : undefined,
    checkOut: typeof meta?.check_out === 'string' ? meta.check_out : undefined,
  };
}

export const MiniCard = memo(function MiniCard({
  tile,
  isSaved = false,
  onDetailsClick,
  onSaveClick,
}: MiniCardProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  // Independent inline expansion state (not accordion)
  const [isExpanded, setIsExpanded] = useState(false);

  const perks = useMemo(() => getPerks(tile), [tile]);
  const priceDisplay = useMemo(() => formatPrice(tile), [tile]);

  // Safety Shield Logic - for flight cards with diving constraints
  const isFlight = isFlightType(tile.type || '');
  const meta = tile.meta as Record<string, unknown> | undefined;
  const isUnsafe = isFlight && meta?.is_safe === false;
  const logicHook = (meta?.logic_hook as string) || undefined;

  // Expanded content data
  const amenities = useMemo(() => getAmenities(tile), [tile]);
  const cancellationText = useMemo(() => getCancellationText(tile), [tile]);
  const checkTimes = useMemo(() => getCheckTimes(tile), [tile]);

  // Card click → opens modal
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

  // Quick facts toggle - stopPropagation to prevent modal open
  const handleQuickFactsToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setIsExpanded((prev) => !prev);
    },
    []
  );

  const quickFactsPanelId = `quickfacts-${tile.id}`;

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
        'relative rounded-lg border bg-card shadow-sm transition-all cursor-pointer',
        // Safety Shield: Zinc border for unsafe flights (warning)
        isUnsafe ? 'border-zinc-500/50 bg-zinc-950/10' : 'border-border',
        'hover:border-border/80 hover:shadow-md hover:translate-y-[-1px]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
        isExpanded && 'ring-1 ring-primary/20'
      )}
    >
      {/* Main content area */}
      <div className="flex items-start gap-3 p-3">
        {/* Thumbnail */}
        <div className="relative h-16 w-16 flex-shrink-0 overflow-hidden rounded-md bg-muted">
          <img
            src={imageError ? placeholderImageForTile(tile) : (tile.image_url || placeholderImageForTile(tile))}
            alt={tile.title}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={cn(
              'h-full w-full object-cover transition-opacity duration-300',
              !imageLoaded && 'opacity-0'
            )}
          />
        </div>

        {/* Content */}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {/* Row 1: Name + Rating + Save */}
          <div className="flex items-start justify-between gap-2">
            <h4 className="line-clamp-1 text-sm font-medium text-card-foreground">
              {tile.title}
            </h4>
            <div className="flex shrink-0 items-center gap-2">
              {tile.rating != null && (
                <div className="flex items-center gap-0.5 text-xs text-muted-foreground">
                  <Star className="h-3 w-3 fill-emerald-400 text-emerald-400" />
                  <span>{tile.rating.toFixed(1)}</span>
                </div>
              )}
              {/* Save button */}
              <button
                type="button"
                onClick={handleSaveClick}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
                  isSaved
                    ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                    : 'text-muted-foreground hover:bg-muted hover:text-card-foreground'
                )}
              >
                <Heart
                  className={cn('h-3 w-3', isSaved && 'fill-emerald-400')}
                />
                {isSaved ? 'In Trip' : 'Add to Trip'}
              </button>
            </div>
          </div>

          {/* Row 2: Area */}
          {tile.location_label && (
            <p className="line-clamp-1 text-xs text-muted-foreground">
              {tile.location_label}
            </p>
          )}

          {/* Row 3: Perk chips */}
          {perks.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {perks.map((perk) => (
                <span
                  key={perk}
                  className={cn(
                    'rounded px-1.5 py-0.5 text-[10px] font-medium',
                    perk === 'Free cancel'
                      ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400'
                      : 'bg-muted text-muted-foreground'
                  )}
                >
                  {perk}
                </span>
              ))}
            </div>
          )}

          {/* Row 4: Price */}
          <div className="mt-1">
            <span className="text-sm font-semibold text-card-foreground">
              {priceDisplay}
            </span>
          </div>

          {/* Logic Hook Chip for flights (Safety Shield) */}
          {isFlight && logicHook && (
            <div className="mt-2">
              <span
                className={cn(
                  'rounded px-1.5 py-0.5 text-[10px] font-medium inline-flex items-center gap-1',
                  meta?.is_safe === false
                    ? 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/20'
                    : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'
                )}
              >
                {logicHook}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Quick facts toggle row - separate from card click */}
      <div className="border-t border-border/50">
        <button
          type="button"
          onClick={handleQuickFactsToggle}
          aria-expanded={isExpanded}
          aria-controls={quickFactsPanelId}
          className="flex w-full items-center gap-1.5 px-3 py-2 min-h-[44px] text-xs text-muted-foreground transition-colors hover:text-foreground hover:bg-muted/50"
        >
          <ChevronDown
            className={cn(
              'h-3 w-3 transition-transform duration-200',
              isExpanded && 'rotate-180'
            )}
          />
          <span>Quick facts</span>
        </button>
      </div>

      {/* Inline expanded content */}
      {isExpanded && (
        <div
          id={quickFactsPanelId}
          className="border-t border-border/50 px-3 pb-3 pt-2 space-y-2"
        >
          {/* Key facts - 2-3 bullets max */}
          {(cancellationText || checkTimes.checkIn || checkTimes.checkOut) && (
            <div className="space-y-1">
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Key facts
              </h5>
              <ul className="space-y-0.5 text-xs text-card-foreground">
                {checkTimes.checkIn && (
                  <li>• Check-in: {checkTimes.checkIn}</li>
                )}
                {checkTimes.checkOut && (
                  <li>• Check-out: {checkTimes.checkOut}</li>
                )}
                {cancellationText && <li>• {cancellationText}</li>}
              </ul>
            </div>
          )}

          {/* Amenities - 4 chips max */}
          {amenities.length > 0 && (
            <div className="space-y-1">
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Amenities
              </h5>
              <div className="flex flex-wrap gap-1">
                {amenities.slice(0, 4).map((amenity) => (
                  <span
                    key={amenity}
                    className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                  >
                    {amenity}
                  </span>
                ))}
                {amenities.length > 4 && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground/70">
                    +{amenities.length - 4} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Provider + Booking Data Tooltip */}
          <div className="flex items-center justify-between">
            {tile.provider && (
              <p className="text-xs text-muted-foreground">
                via {tile.provider}
              </p>
            )}
            {/* Deep Link Params Tooltip (YC Demo: proves real data) */}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={(e) => e.stopPropagation()}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-card-foreground transition-colors"
                  >
                    <Code2 className="h-3 w-3" />
                    <span>API</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs">
                  <p className="text-[10px] text-muted-foreground mb-1 font-medium">
                    Booking API Payload
                  </p>
                  <pre className="text-[10px] font-mono bg-muted/50 rounded p-2 overflow-auto max-h-40">
                    {JSON.stringify(getDeepLinkParams(tile), null, 2)}
                  </pre>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      )}
    </div>
  );
});

export default MiniCard;
