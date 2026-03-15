'use client';

import { ExternalLink, Heart, MapPin, Sparkles, Star } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useState } from 'react';

import {
  getAmenityIconsWithLabels,
  getEffectiveTileDeeplinkUrl,
  getTileDeeplinkPillLabel,
  isPartnerDeeplinkUrl,
} from '@/components/tiles/tileHelpers';
import { trackDeeplinkClick } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { formatTilePrice } from '@/lib/format-utils';
import { placeholderImageForTile } from '@/lib/placeholders';
import { renderStarRating } from '@/lib/renderStarRating';
import { cn } from '@/lib/utils';
import { useDocumentTripInputs } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

import { SuggestionActionRow, SuggestionReasoning } from './suggestionCardSections';

export { renderStarRating } from '@/lib/renderStarRating';

export interface SuggestionCardContentProps {
  tile: Tile;
  reasoning?: string;
  isSaved?: boolean;
  onSave?: (tile: Tile) => void;
  onViewAlternatives?: () => void;
  onDetailsClick?: (tile: Tile) => void;
  className?: string;
}

export function SuggestionCardContent({
  tile,
  reasoning,
  isSaved = false,
  onSave,
  onViewAlternatives,
  onDetailsClick,
  className,
}: SuggestionCardContentProps) {
  const [isReasoningExpanded, setIsReasoningExpanded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const tripInputs = useDocumentTripInputs();

  const isHotel = tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay');
  const amenityIcons = getAmenityIconsWithLabels(tile);

  const priceDisplay = formatTilePrice(tile);
  const deeplinkUrl = getEffectiveTileDeeplinkUrl(tile, tripInputs);

  const placeholderUrl = placeholderImageForTile(tile);
  const imageUrl = imageError ? placeholderUrl : (tile.image_url || placeholderUrl);

  const handleImageError = useCallback(() => {
    setImageError(true);
  }, []);

  return (
    <div
      className={cn(
        'rounded-xl overflow-hidden',
        'bg-white/95 border border-zinc-200 shadow-card',
        'dark:bg-white/5 dark:border-white/10',
        'transition-all duration-150',
        className
      )}
    >
      <div className="relative h-32">
        <Image
          src={imageUrl}
          alt={tile.title}
          fill
          sizes="(max-width: 768px) 100vw, 300px"
          className="object-cover"
          onError={handleImageError}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
        <div className="absolute top-3 left-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/20 backdrop-blur-sm border border-emerald-500/30">
            <Sparkles className="w-3 h-3 text-emerald-400" />
            <span className={`${DS.textSize.micro} font-semibold text-emerald-300 uppercase tracking-wide`}>
              Suggested
            </span>
          </div>
        </div>
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          <button
            onClick={() => onSave?.(tile)}
            aria-label={isSaved ? 'Remove from trip' : 'Save to trip'}
            className={cn(
              'p-2 rounded-full backdrop-blur-sm transition-colors',
              isSaved
                ? 'text-emerald-400 bg-emerald-400/20'
                : 'text-white/70 bg-black/40 hover:text-emerald-400'
            )}
          >
            <Heart className={cn('w-5 h-5', isSaved && 'fill-current')} />
          </button>
        </div>
        <div className="absolute bottom-0 left-0 right-0 p-3">
          <h3 className="text-lg font-semibold text-white drop-shadow-md">{tile.title}</h3>
          {tile.subtitle && <p className="text-sm text-white/80">{tile.subtitle}</p>}
        </div>
      </div>
      <div className="p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {tile.rating && (
              <div className="flex items-center gap-1">
                {isHotel ? (
                  <span className="text-sm text-zinc-500 dark:text-zinc-300">{renderStarRating(tile.rating)}</span>
                ) : (
                  <>
                    <Star className="w-4 h-4 text-zinc-500 dark:text-zinc-300 fill-current" />
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{tile.rating.toFixed(1)}</span>
                  </>
                )}
              </div>
            )}
            {tile.location_label && <span className="text-sm text-zinc-500 dark:text-zinc-400">{tile.location_label}</span>}
            {amenityIcons.length > 0 && (
              <span className="flex gap-0.5 text-sm">
                {amenityIcons.map(({ icon, label }) => (
                  <span key={label} title={label}>
                    {icon}
                  </span>
                ))}
              </span>
            )}
          </div>
          {priceDisplay && <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{priceDisplay}</span>}
        </div>
        {reasoning && (
          <SuggestionReasoning
            reasoning={reasoning}
            isExpanded={isReasoningExpanded}
            onToggle={() => setIsReasoningExpanded(!isReasoningExpanded)}
          />
        )}
        {deeplinkUrl && deeplinkUrl !== '' && deeplinkUrl !== '#' && (() => {
          const isPartner = isPartnerDeeplinkUrl(deeplinkUrl);
          return (
            <a
              href={deeplinkUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => {
                e.stopPropagation();
                trackDeeplinkClick(tile.id);
              }}
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full w-fit',
                'text-xs font-bold uppercase tracking-wide',
                'transition-all duration-150 active:scale-95',
                'bg-emerald-50 border border-emerald-500/30 text-emerald-700',
                'hover:bg-emerald-100 hover:border-emerald-500/60',
                'dark:bg-emerald-950/40 dark:border-emerald-500/25 dark:text-emerald-400',
                'dark:hover:bg-emerald-900/50 dark:hover:border-emerald-400/50',
                'dark:hover:shadow-[0_0_16px_-3px_rgba(16,185,129,0.35)]',
              )}
            >
              {isPartner ? <ExternalLink className="w-3.5 h-3.5" /> : <MapPin className="w-3.5 h-3.5" />}
              {getTileDeeplinkPillLabel(tile, deeplinkUrl)}
            </a>
          );
        })()}
        <SuggestionActionRow
          tile={tile}
          isSaved={isSaved}
          onSave={onSave}
          onViewAlternatives={onViewAlternatives}
          onDetailsClick={onDetailsClick}
        />
      </div>
    </div>
  );
}
