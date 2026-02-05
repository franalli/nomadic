/**
 * SuggestionCard
 *
 * Renders a tile as a "suggestion" with AI reasoning in PLANNING mode.
 * Shows "Why this?" explanation, "Save to Trip" action, and "Change" button.
 *
 * @see docs/ux_unified_architecture.md Section I.B - Booking Suggestions Pattern
 */

'use client';

import { ChevronDown, ChevronUp, Heart, RefreshCw, Settings, Sparkles, Star } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useState } from 'react';

import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

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
  onOpenStaysSettings,
  variant = 'expanded',
  className,
}: SuggestionCardProps) {
  const [isReasoningExpanded, setIsReasoningExpanded] = useState(false);
  const [imageError, setImageError] = useState(false);

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

  // Compact variant - single row
  if (variant === 'compact') {
    return (
      <div
        className={cn(
          'flex items-center gap-3 p-3 rounded-xl',
          // Light: White glass with visible border (Tactile Rule)
          'bg-white/90 border border-zinc-200 shadow-sm',
          'hover:border-zinc-300 hover:shadow-md',
          // Dark: Glass fill with subtle border
          'dark:bg-white/5 dark:border-white/10',
          'dark:hover:bg-white/10 dark:hover:border-white/20',
          'transition-all duration-150',
          className
        )}
      >
        {/* Thumbnail */}
        <div className="relative w-12 h-12 rounded-lg overflow-hidden flex-shrink-0 ring-1 ring-black/5 dark:ring-white/10">
          <Image
            src={imageUrl}
            alt={tile.title}
            fill
            sizes="48px"
            className="object-cover"
            onError={handleImageError}
          />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wide">
              Suggested
            </span>
          </div>
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">{tile.title}</p>
          {tile.subtitle && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400 truncate">{tile.subtitle}</p>
          )}
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

        {/* Settings gear for hotel tiles */}
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

        {/* Save button */}
        <button
          onClick={() => onSave?.(tile)}
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
        'bg-white/95 border border-zinc-200 shadow-md',
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
            <span className="text-[10px] font-semibold text-emerald-300 uppercase tracking-wide">
              Suggested
            </span>
          </div>
        </div>

        {/* Top-right action buttons */}
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          {/* Settings gear for hotel tiles */}
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
          {/* Save button */}
          <button
            onClick={() => onSave?.(tile)}
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
                <Star className="w-4 h-4 text-amber-400 fill-amber-400" />
                <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{tile.rating.toFixed(1)}</span>
              </div>
            )}
            {tile.location_label && (
              <span className="text-sm text-zinc-500 dark:text-zinc-400">{tile.location_label}</span>
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
          <div className="rounded-lg bg-zinc-50 dark:bg-zinc-900/50 border border-zinc-200 dark:border-zinc-700/30">
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
                : 'bg-zinc-900 dark:bg-emerald-600 text-white hover:bg-zinc-800 dark:hover:bg-emerald-500'
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
