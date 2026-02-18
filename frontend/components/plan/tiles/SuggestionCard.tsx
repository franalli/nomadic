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

'use client';

import { ChevronDown, ChevronUp, Heart, RefreshCw, Sparkles, Star } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useMemo, useState } from 'react';

import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isFlightType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

/**
 * Amenity icon mapping for inline display (max 3 shown)
 */
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
  // Curated destination amenities
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

/**
 * Get inline amenity icons with labels (max 3) for hotel tiles
 */
function getAmenityIconsWithLabels(tile: Tile): Array<{ icon: string; label: string }> {
  const meta = tile.meta as Record<string, unknown> | undefined;
  const amenities = (meta?.amenities as string[]) || [];
  const result: Array<{ icon: string; label: string }> = [];
  const seenIcons = new Set<string>();

  for (const amenity of amenities) {
    const key = amenity.toLowerCase();
    const icon = AMENITY_ICONS[key];
    if (icon && !seenIcons.has(icon)) {
      seenIcons.add(icon);
      // Format label: "dive_center_nearby" -> "Dive center nearby"
      const label = amenity.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
      result.push({ icon, label });
      if (result.length >= 3) break;
    }
  }

  return result;
}

/**
 * Render star rating as repeated stars for hotels
 */
function renderStarRating(rating: number): string {
  const stars = Math.round(rating);
  return '★'.repeat(Math.min(stars, 5));
}

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
  const [isReasoningExpanded, setIsReasoningExpanded] = useState(false);
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

  // Expanded variant - full card
  return (
    <div
      className={cn(
        'rounded-xl overflow-hidden',
        // Light: White glass with visible border and shadow
        'bg-white/95 border border-zinc-200 shadow-card',
        // Dark: Glass fill with subtle border
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
        {/* Gradient overlay */}
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
          {/* TODO: Post-demo - wire up hotel filtering
          {onOpenStaysSettings && (tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay')) && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onOpenStaysSettings();
              }}
              className="p-2 rounded-full backdrop-blur-sm transition-colors text-white/70 bg-black/30 hover:text-zinc-200 hover:bg-black/50"
              aria-label="Hotel preferences"
            >
              <Settings className="w-4 h-4" />
            </button>
          )}
          */}
          {/* Save button */}
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
          {formattedPrice && (
            <div className="text-sm">
              <span className="text-zinc-900 dark:text-zinc-100 font-semibold">{formattedPrice}</span>
              {tile.type === 'hotel' && <span className="text-zinc-500 dark:text-zinc-400">/night</span>}
            </div>
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

export default SuggestionCard;
