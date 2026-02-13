/**
 * BookableCard
 *
 * Renders a tile for BOOKING mode with price comparison across partners.
 * Shows prominent pricing, partner logos, and "Book Now" CTAs.
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */

'use client';

import { Check, ExternalLink, Star } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useState } from 'react';

import { formatPrice } from '@/lib/format-utils';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// =============================================================================
// Types
// =============================================================================

export interface PartnerPrice {
  partner: string;
  price: number;
  currency: string;
  url?: string;
  isBestPrice?: boolean;
}

interface BookableCardProps {
  tile: Tile;
  /** Partner prices for comparison */
  partnerPrices?: PartnerPrice[];
  /** Whether this tile is in the cart */
  isInCart?: boolean;
  /** Whether this tile is already booked */
  isBooked?: boolean;
  /** Callback when user books via a partner */
  onBook?: (tile: Tile, partner: string) => void;
  /** Callback to add/remove from cart */
  onCartToggle?: (tile: Tile) => void;
  /** Callback for tile details */
  onDetailsClick?: (tile: Tile) => void;
  className?: string;
}

// =============================================================================
// Partner Logo Mapping
// =============================================================================

const PARTNER_LOGOS: Record<string, { name: string; bgColor: string }> = {
  'booking.com': { name: 'Booking.com', bgColor: 'bg-[#003580]' },
  booking: { name: 'Booking.com', bgColor: 'bg-[#003580]' },
  expedia: { name: 'Expedia', bgColor: 'bg-[#FFD500]' },
  hotels: { name: 'Hotels.com', bgColor: 'bg-[#D32F2F]' },
  'hotels.com': { name: 'Hotels.com', bgColor: 'bg-[#D32F2F]' },
  agoda: { name: 'Agoda', bgColor: 'bg-[#5392F9]' },
  airbnb: { name: 'Airbnb', bgColor: 'bg-[#FF5A5F]' },
  skyscanner: { name: 'Skyscanner', bgColor: 'bg-[#0770E3]' },
  kayak: { name: 'Kayak', bgColor: 'bg-[#FF690F]' },
  direct: { name: 'Direct', bgColor: 'bg-emerald-600' },
};

// =============================================================================
// Helpers
// =============================================================================

function getPartnerInfo(partner: string) {
  const normalized = partner.toLowerCase().replace(/\s+/g, '');
  return (
    PARTNER_LOGOS[normalized] || {
      name: partner,
      bgColor: 'bg-zinc-600',
    }
  );
}

// =============================================================================
// Component
// =============================================================================

export function BookableCard({
  tile,
  partnerPrices = [],
  isInCart = false,
  isBooked = false,
  onBook,
  onCartToggle,
  onDetailsClick,
  className,
}: BookableCardProps) {
  const [imageError, setImageError] = useState(false);

  // Sort prices to show best first
  const sortedPrices = [...partnerPrices].sort((a, b) => a.price - b.price);
  const bestPrice = sortedPrices[0];

  // Get placeholder URL (deterministic based on tile)
  const placeholderUrl = placeholderImageForTile(tile);

  // Get image URL with fallback to Unsplash placeholder
  const imageUrl = imageError
    ? placeholderUrl
    : (tile.image_url || placeholderUrl);

  // Handle image load error
  const handleImageError = useCallback(() => {
    setImageError(true);
  }, []);

  // Determine if hotel (show /night)
  const isHotel = tile.type === 'hotel' || tile.type === 'accommodation';

  return (
    <div
      className={cn(
        'rounded-xl overflow-hidden',
        'bg-zinc-800/40 border',
        isBooked
          ? 'border-emerald-500/50'
          : isInCart
            ? 'border-amber-500/50'
            : 'border-zinc-700/30',
        className
      )}
    >
      {/* Header with image */}
      <div className="relative h-28">
        <Image
          src={imageUrl}
          alt={tile.title}
          fill
          sizes="(max-width: 768px) 100vw, 300px"
          className="object-cover"
          onError={handleImageError}
        />
        {/* Gradient overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />

        {/* Status badge */}
        {isBooked ? (
          <div className="absolute top-3 left-3">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/30 backdrop-blur-sm border border-emerald-500/50">
              <Check className="w-3 h-3 text-emerald-400" />
              <span className="text-[10px] font-semibold text-emerald-300 uppercase tracking-wide">
                Booked
              </span>
            </div>
          </div>
        ) : isInCart ? (
          <div className="absolute top-3 left-3">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/30 backdrop-blur-sm border border-amber-500/50">
              <span className="text-[10px] font-semibold text-amber-300 uppercase tracking-wide">
                In Cart
              </span>
            </div>
          </div>
        ) : null}

        {/* Title overlay */}
        <div className="absolute bottom-0 left-0 right-0 p-3">
          <h3 className="text-base font-semibold text-white drop-shadow-md line-clamp-1">
            {tile.title}
          </h3>
          {tile.subtitle && (
            <p className="text-sm text-white/70 line-clamp-1">{tile.subtitle}</p>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {/* Rating row */}
        {tile.rating && (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <Star className="w-4 h-4 text-amber-400 fill-amber-400" />
              <span className="text-sm font-medium text-zinc-200">
                {tile.rating.toFixed(1)}
              </span>
            </div>
            {tile.location_label && (
              <span className="text-sm text-zinc-400">{tile.location_label}</span>
            )}
          </div>
        )}

        {/* Best price highlight */}
        {bestPrice && (
          <div className="flex items-baseline justify-between">
            <div>
              <span className="text-2xl font-bold text-white">
                {formatPrice(bestPrice.price, bestPrice.currency)}
              </span>
              {isHotel && <span className="text-sm text-zinc-400">/night</span>}
            </div>
            {sortedPrices.length > 1 && (
              <span className="text-xs text-zinc-500">
                from {sortedPrices.length} partners
              </span>
            )}
          </div>
        )}

        {/* Partner price comparison */}
        {sortedPrices.length > 0 && (
          <div className="space-y-2">
            {sortedPrices.slice(0, 3).map((pp, index) => {
              const partnerInfo = getPartnerInfo(pp.partner);
              const isBest = index === 0;

              return (
                <div
                  key={pp.partner}
                  className={cn(
                    'flex items-center justify-between p-2 rounded-lg transition-colors',
                    isBest
                      ? 'bg-emerald-500/10 border border-emerald-500/30'
                      : 'bg-zinc-800/50 hover:bg-zinc-700/50'
                  )}
                >
                  {/* Partner info */}
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        'w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold text-white',
                        partnerInfo.bgColor
                      )}
                    >
                      {partnerInfo.name.charAt(0)}
                    </div>
                    <span className="text-sm text-zinc-300">{partnerInfo.name}</span>
                    {isBest && (
                      <span className="text-[10px] font-medium text-emerald-400 uppercase">
                        Best Price
                      </span>
                    )}
                  </div>

                  {/* Price and book button */}
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'text-sm font-medium',
                        isBest ? 'text-emerald-400' : 'text-zinc-300'
                      )}
                    >
                      {formatPrice(pp.price, pp.currency)}
                    </span>
                    <button
                      onClick={() => onBook?.(tile, pp.partner)}
                      disabled={isBooked}
                      className={cn(
                        'flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors',
                        isBooked
                          ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
                          : isBest
                            ? 'bg-emerald-600 text-white hover:bg-emerald-500'
                            : 'bg-zinc-700 text-zinc-300 hover:bg-zinc-600'
                      )}
                    >
                      Book
                      <ExternalLink className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* No partner prices - show fallback */}
        {sortedPrices.length === 0 && tile.price_estimate && (
          <div className="p-3 rounded-lg bg-zinc-800/50 text-center">
            <span className="text-lg font-bold text-white">
              {formatPrice(tile.price_estimate)}
            </span>
            {isHotel && <span className="text-sm text-zinc-400">/night</span>}
            <p className="text-xs text-zinc-500 mt-1">Price comparison loading...</p>
          </div>
        )}

        {/* Action row */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => onDetailsClick?.(tile)}
            className="flex-1 px-3 py-2 rounded-lg text-sm font-medium text-zinc-300 bg-zinc-700/50 hover:bg-zinc-700 transition-colors text-center"
          >
            View Details
          </button>
          {!isBooked && (
            <button
              onClick={() => onCartToggle?.(tile)}
              className={cn(
                'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                isInCart
                  ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30'
                  : 'bg-zinc-700/50 text-zinc-300 hover:bg-zinc-700'
              )}
            >
              {isInCart ? 'Remove' : 'Add to Cart'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default BookableCard;
