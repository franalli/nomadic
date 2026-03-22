'use client';

import { Heart, Plane } from 'lucide-react';
import Image from 'next/image';
import { useState } from 'react';

import {
  getEffectiveTileDeeplinkUrl,
  getTileDeeplinkPillLabel,
  isPartnerDeeplinkUrl,
} from '@/components/tiles/tileHelpers';
import { trackEvent } from '@/lib/analytics';
import { trackDeeplinkClick } from '@/lib/api-streaming';
import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isFlightType } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

interface TileRailCardProps {
  tile: Tile;
  isSaved: boolean;
  onSave?: (tile: Tile) => void;
  onDetailsClick?: (tile: Tile) => void;
}

export function TileRailCard({ tile, isSaved, onSave, onDetailsClick }: TileRailCardProps) {
  const [imageError, setImageError] = useState(false);
  const tripInputs = useDocumentTripInputs();

  const isHotel = tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay');
  const isFlight = isFlightType(tile.type || '');
  const price = tile.total_inclusive ?? tile.price_estimate;
  const formattedPrice = price ? `$${price.toLocaleString()}` : null;
  const placeholderUrl = placeholderImageForTile(tile);
  const imageUrl = imageError ? placeholderUrl : (tile.image_url || placeholderUrl);
  const deeplinkUrl = getEffectiveTileDeeplinkUrl(tile, tripInputs);
  const hasDeeplink = Boolean(deeplinkUrl && deeplinkUrl !== '#');
  const isPartner = hasDeeplink && deeplinkUrl ? isPartnerDeeplinkUrl(deeplinkUrl) : false;

  return (
    <div
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onDetailsClick?.(tile); } }}
      className={cn(
        'relative flex-shrink-0 snap-start overflow-hidden rounded-xl border cursor-pointer',
        'border-zinc-200 bg-white/90 shadow-card transition-all duration-150',
        'hover:border-zinc-300 hover:shadow-soft',
        'dark:border-white/10 dark:bg-white/5 dark:hover:border-white/20 dark:hover:bg-white/10',
        isHotel ? DS.tileRail.hotelWidth : DS.tileRail.activityWidth,
      )}
      onClick={() => onDetailsClick?.(tile)}
    >
      {/* Suggested badge */}
      <span className={cn("absolute top-1.5 left-1.5 z-10 rounded px-1.5 py-0.5 font-bold uppercase tracking-wider bg-emerald-500/90 text-white", DS.textSize.nano)}>
        Suggested
      </span>

      {/* Image area */}
      {isHotel && (
        <div className={cn('relative w-full overflow-hidden', DS.tileRail.imageHeight)}>
          <Image
            src={imageUrl}
            alt={tile.title || 'Hotel image'}
            fill
            sizes="220px"
            className="object-cover"
            onError={() => setImageError(true)}
          />
        </div>
      )}
      {isFlight && (
        <div className="relative flex h-12 items-center justify-center bg-zinc-50 dark:bg-white/[0.02]">
          {tile.image_url && !imageError ? (
            <Image
              src={imageUrl}
              alt={tile.title || 'Flight image'}
              width={36}
              height={36}
              className="h-9 w-9 object-contain"
              onError={() => setImageError(true)}
            />
          ) : (
            <Plane className="h-5 w-5 text-zinc-400" />
          )}
        </div>
      )}

      {/* Content */}
      <div className="p-2.5 space-y-1">
        <p className={cn(DS.textSize.micro, 'font-medium truncate text-zinc-900 dark:text-zinc-100')}>
          {tile.title}
        </p>
        {tile.subtitle && (
          <p className={cn(DS.textSize.mini, 'text-zinc-500 dark:text-zinc-400 truncate')}>
            {tile.subtitle}
          </p>
        )}
        <div className="flex items-center justify-between">
          {formattedPrice && (
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {formattedPrice}
              {isHotel && <span className={cn(DS.textSize.mini, 'font-normal text-zinc-500 dark:text-zinc-400')}>/night</span>}
            </span>
          )}
          {isHotel && tile.rating != null && (
            <span className={cn(DS.textSize.mini, 'text-zinc-500 dark:text-zinc-400')}>
              {tile.rating}★
            </span>
          )}
        </div>
        {hasDeeplink && deeplinkUrl && (
          <a
            href={deeplinkUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              e.stopPropagation();
              trackDeeplinkClick(tile.id);
              trackEvent('deeplink_clicked', tripInputs?.destination, {
                provider: tile.provider ?? 'other',
                tile_type: tile.type,
                tile_id: tile.id,
                price: tile.total_inclusive ?? tile.price_estimate,
              });
            }}
            className={cn(
              DS.textSize.mini, 'font-medium',
              'text-emerald-600 dark:text-emerald-400 hover:underline'
            )}
          >
            {isPartner ? getTileDeeplinkPillLabel(tile, deeplinkUrl) : 'View →'}
          </a>
        )}
      </div>

      {/* Heart button */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onSave?.(tile);
        }}
        aria-label={isSaved ? 'Remove from trip' : 'Save to trip'}
        className={cn(
          'absolute top-1.5 right-1.5 rounded-full p-1.5 transition-colors',
          isSaved
            ? 'bg-emerald-500/20 text-emerald-500'
            : 'bg-black/20 text-white hover:bg-black/40 dark:bg-white/20 dark:hover:bg-white/30'
        )}
      >
        <Heart className={cn('h-3.5 w-3.5', isSaved && 'fill-current')} />
      </button>
    </div>
  );
}
