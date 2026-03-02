'use client';

import { ChevronDown, ChevronUp, Heart, MapPin, RefreshCw, Sparkles, Star } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useState } from 'react';

import { trackDeeplinkClick } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { formatTilePrice } from '@/lib/format-utils';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// =============================================================================
// Helpers (shared with SuggestionCard)
// =============================================================================

const AMENITY_ICONS: Record<string, string> = {
  pool: '🏊',
  'swimming pool': '🏊',
  breakfast: '🍳',
  'breakfast included': '🍳',
  wifi: '📶',
  'free wifi': '📶',
  parking: '🅿️',
  'free parking': '🅿️',
  spa: '💆',
  gym: '🏋️',
  fitness: '🏋️',
  'fitness center': '🏋️',
  restaurant: '🍽️',
  bar: '🍸',
  'air conditioning': '❄️',
  'pet friendly': '🐕',
  beach: '🏖️',
  yoga: '🧘',
  dive_center: '🤿',
  dive_center_nearby: '🤿',
  ski_room: '🎿',
  rooftop_bar: '🍸',
  garden: '🌿',
  valley_view: '🏞️',
  lake_view: '🏞️',
  horseback: '🐴',
  guided_hikes: '🥾',
};

export function getAmenityIconsWithLabels(tile: Tile): Array<{ icon: string; label: string }> {
  const meta = tile.meta as Record<string, unknown> | undefined;
  const amenities = (meta?.amenities as string[]) || [];
  const result: Array<{ icon: string; label: string }> = [];
  const seenIcons = new Set<string>();

  for (const amenity of amenities) {
    const key = amenity.toLowerCase();
    const icon = AMENITY_ICONS[key];
    if (icon && !seenIcons.has(icon)) {
      seenIcons.add(icon);
      const label = amenity.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
      result.push({ icon, label });
      if (result.length >= 3) break;
    }
  }

  return result;
}

export function renderStarRating(rating: number): string {
  const stars = Math.round(rating);
  return '★'.repeat(Math.min(stars, 5));
}

// =============================================================================
// Types
// =============================================================================

export interface SuggestionCardContentProps {
  tile: Tile;
  /** AI reasoning for why this tile was suggested */
  reasoning?: string;
  /** Whether tile is saved to trip */
  isSaved?: boolean;
  /** Callback when user saves/unsaves */
  onSave?: (tile: Tile) => void;
  /** Callback to view alternatives */
  onViewAlternatives?: () => void;
  /** Callback for tile details */
  onDetailsClick?: (tile: Tile) => void;
  className?: string;
}

// =============================================================================
// Component — Expanded variant card body
// =============================================================================

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

  const isHotel = tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay');
  const amenityIcons = getAmenityIconsWithLabels(tile);

  const priceDisplay = formatTilePrice(tile);

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
      {/* Header with image */}
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

        {/* Suggested badge */}
        <div className="absolute top-3 left-3">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/20 backdrop-blur-sm border border-emerald-500/30">
            <Sparkles className="w-3 h-3 text-emerald-400" />
            <span className={`${DS.textSize.micro} font-semibold text-emerald-300 uppercase tracking-wide`}>
              Suggested
            </span>
          </div>
        </div>

        {/* Top-right action buttons */}
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          <button
            onClick={() => onSave?.(tile)}
            aria-label={isSaved ? 'Remove from trip' : 'Save to trip'}
            className={cn(
              'p-2 rounded-full backdrop-blur-sm transition-colors',
              isSaved
                ? 'text-emerald-400 bg-emerald-400/20'
                : 'text-white/70 bg-black/30 hover:text-emerald-400'
            )}
          >
            <Heart className={cn('w-5 h-5', isSaved && 'fill-current')} />
          </button>
        </div>

        {/* Title overlay */}
        <div className="absolute bottom-0 left-0 right-0 p-3">
          <h3 className="text-lg font-semibold text-white drop-shadow-md">
            {tile.title}
          </h3>
          {tile.subtitle && (
            <p className="text-sm text-white/80">{tile.subtitle}</p>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="p-4 space-y-3">
        {/* Rating and price row */}
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
            {tile.location_label && (
              <span className="text-sm text-zinc-500 dark:text-zinc-400">{tile.location_label}</span>
            )}
            {amenityIcons.length > 0 && (
              <span className="flex gap-0.5 text-sm">
                {amenityIcons.map(({ icon, label }) => (
                  <span key={label} title={label} >{icon}</span>
                ))}
              </span>
            )}
          </div>
          {priceDisplay && (
            <span className="text-sm text-zinc-900 dark:text-zinc-100 font-semibold">
              {priceDisplay}
            </span>
          )}
        </div>

        {/* Why this suggestion? - Expandable */}
        {reasoning && (
          <div className="rounded-lg bg-zinc-50 dark:bg-white/[0.03] border border-zinc-200 dark:border-white/5">
            <button
              onClick={() => setIsReasoningExpanded(!isReasoningExpanded)}
              className="w-full flex items-center justify-between p-3 text-left"
            >
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Why this suggestion?</span>
              </div>
              {isReasoningExpanded ? (
                <ChevronUp className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
            </button>
            {isReasoningExpanded && (
              <div className="px-3 pb-3">
                <p className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">{reasoning}</p>
              </div>
            )}
          </div>
        )}

        {/* Deeplink pill */}
        {tile.deeplink_url && tile.deeplink_url !== '' && tile.deeplink_url !== '#' && (
          <a
            href={tile.deeplink_url}
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
            <MapPin className="w-3.5 h-3.5" />
            View on Google
          </a>
        )}

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={onViewAlternatives}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-zinc-700 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-700/50 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Change
          </button>
          <button
            onClick={() => onDetailsClick?.(tile)}
            className="flex-1 px-3 py-2 rounded-lg text-sm font-medium text-zinc-700 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-700/50 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors text-center"
          >
            View Details
          </button>
          <button
            onClick={() => onSave?.(tile)}
            className={cn(
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              isSaved
                ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                : DS.actions.primary
            )}
          >
            {isSaved ? 'Saved' : 'Save to Trip'}
          </button>
        </div>
      </div>
    </div>
  );
}
