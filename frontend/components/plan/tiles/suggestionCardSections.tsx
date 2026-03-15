'use client';

import { ChevronDown, ChevronUp, ExternalLink, Heart, MapPin, RefreshCw, Sparkles } from 'lucide-react';
import Image from 'next/image';
import { useState } from 'react';

import {
  getAmenityIconsWithLabels,
  getEffectiveTileDeeplinkUrl,
  getTileDeeplinkPillLabel,
  isPartnerDeeplinkUrl,
} from '@/components/tiles/tileHelpers';
import { trackDeeplinkClick } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { renderStarRating } from '@/lib/renderStarRating';
import { cn, isFlightType } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

export function SuggestionCardCompact({
  tile,
  isSaved,
  onSave,
  className,
}: {
  tile: Tile;
  isSaved: boolean;
  onSave?: (tile: Tile) => void;
  className?: string;
}) {
  const [imageError, setImageError] = useState(false);
  const tripInputs = useDocumentTripInputs();
  const amenityIcons = getAmenityIconsWithLabels(tile);
  const isHotel = tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay');
  const price = tile.price_estimate ?? tile.total_inclusive;
  const formattedPrice = price ? `$${price.toLocaleString()}` : null;
  const placeholderUrl = placeholderImageForTile(tile);
  const imageUrl = imageError ? placeholderUrl : (tile.image_url || placeholderUrl);
  const isFlight = isFlightType(tile.type || '');
  const thumbnailContainerClass = isFlight
    ? 'flex h-12 w-12 items-center justify-center rounded-xl bg-white ring-1 ring-black/5'
    : isHotel
      ? 'h-16 w-24 rounded-xl ring-1 ring-black/5 dark:ring-white/10'
      : 'h-12 w-12 rounded-lg ring-1 ring-black/5 dark:ring-white/10';
  const thumbnailSize = isFlight ? '48px' : isHotel ? '96px' : '48px';
  const deeplinkUrl = getEffectiveTileDeeplinkUrl(tile, tripInputs);
  const hasDeeplink = Boolean(deeplinkUrl && deeplinkUrl !== '#');
  const isPartner = hasDeeplink && deeplinkUrl ? isPartnerDeeplinkUrl(deeplinkUrl) : false;

  return (
    <div
      className={cn(
        'flex items-center gap-4 rounded-xl border border-zinc-200 bg-white/90 p-4 shadow-card transition-all duration-150',
        'hover:border-zinc-300 hover:shadow-soft dark:border-white/10 dark:bg-white/5 dark:hover:border-white/20 dark:hover:bg-white/10',
        className
      )}
    >
      <div
        className={cn(
          'relative flex-shrink-0 overflow-hidden',
          thumbnailContainerClass
        )}
      >
        <Image
          src={imageUrl}
          alt={tile.title}
          fill={!isFlight}
          width={isFlight ? 36 : undefined}
          height={isFlight ? 36 : undefined}
          sizes={thumbnailSize}
          className={isFlight ? 'h-9 w-9 object-contain' : 'object-cover'}
          onError={() => setImageError(true)}
        />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className={`${DS.textSize.micro} font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400`}>Suggested</span>
          {isHotel && tile.rating != null && (
            <span className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-300`}>{renderStarRating(tile.rating)}</span>
          )}
        </div>
        <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{tile.title}</p>
        <div className="flex items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400">
          {tile.subtitle && <span className="truncate">{tile.subtitle}</span>}
          {amenityIcons.length > 0 && (
            <>
              {tile.subtitle && <span className="text-zinc-400 dark:text-zinc-500">·</span>}
              <span className="flex gap-0.5">
                {amenityIcons.map(({ icon, label }) => (
                  <span key={label} title={label}>
                    {icon}
                  </span>
                ))}
              </span>
            </>
          )}
        </div>
      </div>

      {formattedPrice && (
        <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          {formattedPrice}
          {(tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay')) && <span className="font-normal text-zinc-500 dark:text-zinc-400">/night</span>}
        </div>
      )}

      {hasDeeplink && deeplinkUrl && (
        <a
          href={deeplinkUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => {
            event.stopPropagation();
            trackDeeplinkClick(tile.id);
          }}
          className={cn(
            'inline-flex shrink-0 self-center rounded-full border border-emerald-500/30 bg-emerald-50 px-2 py-1',
            'items-center gap-1 text-emerald-700 transition-all duration-150 active:scale-95',
            `${DS.textSize.micro} font-bold uppercase tracking-wider`,
            'hover:border-emerald-500/60 hover:bg-emerald-100 dark:border-emerald-500/25 dark:bg-emerald-950/40 dark:text-emerald-400',
            'dark:hover:border-emerald-400/50 dark:hover:bg-emerald-900/50 dark:hover:shadow-[0_0_12px_-3px_rgba(16,185,129,0.3)]',
          )}
        >
          {isPartner ? <ExternalLink className="h-3 w-3" /> : <MapPin className="h-3 w-3" />}
          {getTileDeeplinkPillLabel(tile, deeplinkUrl)}
        </a>
      )}

      <button
        onClick={() => onSave?.(tile)}
        aria-label={isSaved ? 'Remove from trip' : 'Save to trip'}
        className={cn(
          'rounded-full p-2 transition-colors',
          isSaved ? 'bg-emerald-500/10 text-emerald-500' : 'text-zinc-400 hover:bg-zinc-100 hover:text-emerald-500 dark:hover:bg-white/10'
        )}
      >
        <Heart className={cn('h-4 w-4', isSaved && 'fill-current')} />
      </button>
    </div>
  );
}
export function SuggestionReasoning({ reasoning, isExpanded, onToggle }: { reasoning: string; isExpanded: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 dark:border-white/5 dark:bg-white/[0.03]">
      <button onClick={onToggle} className="flex w-full items-center justify-between p-3 text-left">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-emerald-500 dark:text-emerald-400" />
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Why this suggestion?</span>
        </div>
        {isExpanded ? <ChevronUp className="h-4 w-4 text-zinc-400" /> : <ChevronDown className="h-4 w-4 text-zinc-400" />}
      </button>
      {isExpanded && (
        <div className="px-3 pb-3">
          <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{reasoning}</p>
        </div>
      )}
    </div>
  );
}

export function SuggestionActionRow({
  tile,
  isSaved,
  onSave,
  onViewAlternatives,
  onDetailsClick,
}: {
  tile: Tile;
  isSaved: boolean;
  onSave?: (tile: Tile) => void;
  onViewAlternatives?: () => void;
  onDetailsClick?: (tile: Tile) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={onViewAlternatives}
        className="flex items-center gap-1.5 rounded-lg bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:bg-zinc-700/50 dark:text-zinc-300 dark:hover:bg-zinc-700"
      >
        <RefreshCw className="h-4 w-4" />
        Change
      </button>
      <button
        onClick={() => onDetailsClick?.(tile)}
        className="flex-1 rounded-lg bg-zinc-100 px-3 py-2 text-center text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-200 dark:bg-zinc-700/50 dark:text-zinc-300 dark:hover:bg-zinc-700"
      >
        View Details
      </button>
      <button
        onClick={() => onSave?.(tile)}
        className={cn(
          'rounded-lg px-4 py-2 text-sm font-medium transition-colors',
          isSaved
            ? 'border border-emerald-500/30 bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
            : DS.actions.primary
        )}
      >
        {isSaved ? 'Saved' : 'Save to Trip'}
      </button>
    </div>
  );
}
