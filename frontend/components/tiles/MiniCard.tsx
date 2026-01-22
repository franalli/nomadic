/**
 * MiniCard
 *
 * Compact tile card for S2 (Plan) discovery view.
 * Shows enough info to evaluate: thumbnail, name, area, rating, price, perks.
 * Actions: Details (opens modal) + Save (adds to shortlist) + View deal (locked until S3)
 *
 * Preview mode (S2):
 * - Shows "Preview" label on card
 * - View deal button is locked with tooltip
 *
 * Booking mode (S3):
 * - No preview label
 * - View deal button is enabled
 */

'use client';

import { ExternalLink, Heart, Info, Lock, Star } from 'lucide-react';
import { memo, useCallback, useMemo, useState } from 'react';

import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

export interface MiniCardProps {
  tile: Tile;
  isSaved?: boolean;
  /** Show "Preview" label (for S2 discovery) */
  showPreviewLabel?: boolean;
  /** Whether booking links are unlocked (S3) */
  isBookingUnlocked?: boolean;
  onDetailsClick?: (tile: Tile) => void;
  onSaveClick?: (tile: Tile) => void;
}

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
 * Get review count from meta
 */
function getReviewCount(tile: Tile): number | null {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (typeof meta?.review_count === 'number') return meta.review_count;
  if (typeof meta?.reviews === 'number') return meta.reviews;
  return null;
}

export const MiniCard = memo(function MiniCard({
  tile,
  isSaved = false,
  showPreviewLabel = false,
  isBookingUnlocked = false,
  onDetailsClick,
  onSaveClick,
}: MiniCardProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);

  const perks = useMemo(() => getPerks(tile), [tile]);
  const priceDisplay = useMemo(() => formatPrice(tile), [tile]);
  const reviewCount = useMemo(() => getReviewCount(tile), [tile]);

  const handleDetailsClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onDetailsClick?.(tile);
    },
    [onDetailsClick, tile]
  );

  const handleSaveClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onSaveClick?.(tile);
    },
    [onSaveClick, tile]
  );

  const handleViewDealClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (!isBookingUnlocked || !tile.deeplink_url) return;
      window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
    },
    [isBookingUnlocked, tile.deeplink_url]
  );

  return (
    <div className="relative flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 transition-colors hover:bg-zinc-800/50">
      {/* Preview label (S2 only) */}
      {showPreviewLabel && (
        <div className="absolute right-2 top-2 rounded bg-zinc-800/90 px-1.5 py-0.5 text-[10px] font-medium text-zinc-400">
          Preview
        </div>
      )}

      {/* Thumbnail - use Unsplash placeholder if no image_url */}
      <div className="relative h-16 w-16 flex-shrink-0 overflow-hidden rounded-md bg-zinc-800">
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
        {/* Row 1: Name + Rating */}
        <div className="flex items-start justify-between gap-2">
          <h4 className="line-clamp-1 text-sm font-medium text-zinc-200">
            {tile.title}
          </h4>
          {tile.rating != null && (
            <div className="flex shrink-0 items-center gap-0.5 text-xs text-zinc-400">
              <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
              <span>{tile.rating.toFixed(1)}</span>
              {reviewCount != null && (
                <span className="text-zinc-500">({reviewCount})</span>
              )}
            </div>
          )}
        </div>

        {/* Row 2: Area */}
        {tile.location_label && (
          <p className="line-clamp-1 text-xs text-zinc-500">
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
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : 'bg-zinc-800 text-zinc-400'
                )}
              >
                {perk}
              </span>
            ))}
          </div>
        )}

        {/* Row 4: Price + Actions */}
        <div className="mt-1 flex items-center justify-between gap-2">
          <span className="text-sm font-semibold text-zinc-200">
            {priceDisplay}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={handleDetailsClick}
              className="flex items-center gap-1 rounded px-2 py-1 text-xs text-zinc-400 transition-colors hover:bg-zinc-700 hover:text-zinc-200"
            >
              <Info className="h-3 w-3" />
              Details
            </button>
            <button
              type="button"
              onClick={handleSaveClick}
              className={cn(
                'flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
                isSaved
                  ? 'bg-amber-500/20 text-amber-400'
                  : 'text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200'
              )}
            >
              <Heart
                className={cn('h-3 w-3', isSaved && 'fill-amber-400')}
              />
              {isSaved ? 'Saved' : 'Save'}
            </button>
            {/* View deal - locked until S3 */}
            <button
              type="button"
              onClick={handleViewDealClick}
              disabled={!isBookingUnlocked}
              title={!isBookingUnlocked ? 'Unlocks after itinerary' : 'Open booking link'}
              className={cn(
                'flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
                isBookingUnlocked
                  ? 'bg-amber-500 text-white hover:bg-amber-600'
                  : 'cursor-not-allowed bg-zinc-800 text-zinc-500'
              )}
            >
              {isBookingUnlocked ? (
                <ExternalLink className="h-3 w-3" />
              ) : (
                <Lock className="h-3 w-3" />
              )}
              View deal
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});

export default MiniCard;
