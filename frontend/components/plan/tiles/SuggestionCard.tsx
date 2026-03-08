'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * SuggestionCard
 *
 * Renders a tile as a "suggestion" with AI reasoning in PLANNING mode.
 * Shows "Why this?" explanation, "Save to Trip" action, and "Change" button.
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */


import { ExternalLink, Heart, MapPin } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useMemo, useState } from 'react';

import { trackDeeplinkClick } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { getAmenityIconsWithLabels, renderStarRating, SuggestionCardContent } from './SuggestionCardContent';

// =============================================================================
// Types
// =============================================================================

interface SuggestionCardProps {
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
  /** Callback to open stays settings sheet (for hotel tiles) */
  onOpenStaysSettings?: () => void;
  /** Compact or expanded variant */
  variant?: 'compact' | 'expanded';
  className?: string;
}

// =============================================================================
// Component
// =============================================================================

export function SuggestionCard({
  tile,
  reasoning,
  isSaved = false,
  onSave,
  onViewAlternatives,
  onDetailsClick,
  onOpenStaysSettings: _onOpenStaysSettings,
  variant = 'expanded',
  className,
}: SuggestionCardProps) {
  const [imageError, setImageError] = useState(false);

  // Memoize amenity icons with labels for tooltips
  const amenityIcons = useMemo(() => getAmenityIconsWithLabels(tile), [tile]);
  const isHotel = tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay');

  // Format price
  const price = tile.price_estimate ?? tile.total_inclusive;
  const formattedPrice = price ? `$${price.toLocaleString()}` : null;

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

  // Detect flight tiles for special logo handling
  const isFlight = isFlightType(tile.type || '');

  // Compact variant - single row
  if (variant === 'compact') {
    return (
      <div
        className={cn(
          'flex items-center gap-3 p-3 rounded-xl',
          // Light: White glass with visible border (Tactile Rule)
          'bg-white/90 border border-zinc-200 shadow-card',
          'hover:border-zinc-300 hover:shadow-soft',
          // Dark: Glass fill with subtle border
          'dark:bg-white/5 dark:border-white/10',
          'dark:hover:bg-white/10 dark:hover:border-white/20',
          'transition-all duration-150',
          className
        )}
      >
        {/* Thumbnail - white circle for flight logos (transparent PNGs from avs.io) */}
        <div className={cn(
          'relative flex-shrink-0 overflow-hidden',
          isFlight
            ? 'w-10 h-10 rounded-full bg-white flex items-center justify-center ring-1 ring-black/5'
            : 'w-12 h-12 rounded-lg ring-1 ring-black/5 dark:ring-white/10'
        )}>
          <Image
            src={imageUrl}
            alt={tile.title}
            fill={!isFlight}
            width={isFlight ? 32 : undefined}
            height={isFlight ? 32 : undefined}
            sizes={isFlight ? '32px' : '48px'}
            className={isFlight ? 'object-contain' : 'object-cover'}
            onError={handleImageError}
          />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={`${DS.textSize.micro} font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wide`}>
              Suggested
            </span>
            {/* Star rating for hotels */}
            {isHotel && tile.rating != null && (
              <span className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-300`}>{renderStarRating(tile.rating)}</span>
            )}
          </div>
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">{tile.title}</p>
          {/* Location + amenity icons */}
          <div className="flex items-center gap-1 text-xs text-zinc-500 dark:text-zinc-400">
            {tile.subtitle && <span className="truncate">{tile.subtitle}</span>}
            {amenityIcons.length > 0 && (
              <>
                {tile.subtitle && <span className="text-zinc-300 dark:text-zinc-600">·</span>}
                <span className="flex gap-0.5">
                  {amenityIcons.map(({ icon, label }) => (
                    <span key={label} title={label} >{icon}</span>
                  ))}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Price */}
        {formattedPrice && (
          <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
            {formattedPrice}
            {(tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay')) && (
              <span className="font-normal text-zinc-500 dark:text-zinc-400">/night</span>
            )}
          </div>
        )}

        {/* TODO: Post-demo - wire up hotel filtering
        {onOpenStaysSettings && (tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay')) && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onOpenStaysSettings();
            }}
            className="p-2 rounded-full transition-colors text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 dark:hover:text-zinc-200 dark:hover:bg-white/10"
            aria-label="Hotel preferences"
          >
            <Settings className="w-4 h-4" />
          </button>
        )}
        */}

        {/* Deeplink VIEW pill */}
        {tile.deeplink_url && tile.deeplink_url !== '' && tile.deeplink_url !== '#' && (() => {
          const isViator = tile.deeplink_url.includes('viator.com');
          return (
            <a
              href={tile.deeplink_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => {
                e.stopPropagation();
                trackDeeplinkClick(tile.id);
              }}
              className={cn(
                'inline-flex items-center gap-1 px-2 py-1 rounded-full self-center shrink-0',
                'text-[10px] font-bold uppercase tracking-wider',
                'transition-all duration-150 active:scale-95',
                'bg-emerald-50 border border-emerald-500/30 text-emerald-700',
                'hover:bg-emerald-100 hover:border-emerald-500/60',
                'dark:bg-emerald-950/40 dark:border-emerald-500/25 dark:text-emerald-400',
                'dark:hover:bg-emerald-900/50 dark:hover:border-emerald-400/50',
                'dark:hover:shadow-[0_0_12px_-3px_rgba(16,185,129,0.3)]',
              )}
          >
            {isViator ? <ExternalLink className="w-3 h-3" /> : <MapPin className="w-3 h-3" />}
            {isViator ? 'Book' : 'Map'}
          </a>
          );
        })()}

        {/* Save button */}
        <button
          onClick={() => onSave?.(tile)}
          aria-label={isSaved ? 'Remove from trip' : 'Save to trip'}
          className={cn(
            'p-2 rounded-full transition-colors',
            isSaved
              ? 'text-emerald-500 bg-emerald-500/10'
              : 'text-zinc-400 hover:text-emerald-500 hover:bg-zinc-100 dark:hover:bg-white/10'
          )}
        >
          <Heart className={cn('w-4 h-4', isSaved && 'fill-current')} />
        </button>
      </div>
    );
  }

  // Expanded variant - full card (extracted to SuggestionCardContent)
  return (
    <SuggestionCardContent
      tile={tile}
      reasoning={reasoning}
      isSaved={isSaved}
      onSave={onSave}
      onViewAlternatives={onViewAlternatives}
      onDetailsClick={onDetailsClick}
      className={className}
    />
  );
}

export default SuggestionCard;
