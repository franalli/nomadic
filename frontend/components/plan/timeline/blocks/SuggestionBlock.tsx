/**
 * SuggestionBlock
 *
 * Timeline block for AI-suggested bookable items (hotels, flights).
 * Shows "Suggested: Hotel Tugu Bali" with "Change" action.
 * Used in PLANNING mode to show recommended options.
 *
 * @see docs/ux_unified_architecture.md Section I.B
 */

'use client';

import { Bed, Check, Plane, RefreshCw, Sparkles } from 'lucide-react';
import Image from 'next/image';

import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

// =============================================================================
// Types
// =============================================================================

interface SuggestionBlockProps {
  /** The suggested tile */
  tile: Tile;
  /** Type of suggestion */
  suggestionType: 'hotel' | 'flight' | 'activity';
  /** Date range for hotels */
  dateRange?: string;
  /** Flight times */
  flightTimes?: { departure: string; arrival: string };
  /** Whether user has confirmed this suggestion */
  isConfirmed?: boolean;
  /** Callback when user wants to change */
  onChangeClick?: () => void;
  /** Callback when user confirms */
  onConfirmClick?: () => void;
  /** Extra ID for map sync */
  id?: string;
  className?: string;
}

// =============================================================================
// Component
// =============================================================================

export function SuggestionBlock({
  tile,
  suggestionType,
  dateRange,
  flightTimes,
  isConfirmed = false,
  onChangeClick,
  onConfirmClick,
  id,
  className,
}: SuggestionBlockProps) {
  const Icon = suggestionType === 'hotel' ? Bed : suggestionType === 'flight' ? Plane : Sparkles;

  // Color theming by type
  const typeColors = {
    hotel: {
      badge: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
      icon: 'text-purple-400',
      indicator: 'bg-purple-500',
    },
    flight: {
      badge: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      icon: 'text-blue-400',
      indicator: 'bg-blue-500',
    },
    activity: {
      badge: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      icon: 'text-emerald-400',
      indicator: 'bg-emerald-500',
    },
  };

  const colors = typeColors[suggestionType];

  // Get image URL with fallback
  const imageUrl = tile.image_url || '/assets/placeholder-tile.jpg';

  return (
    <div
      id={id}
      className={cn(
        'relative flex gap-4 p-4 rounded-xl transition-all',
        'bg-zinc-800/30 border',
        isConfirmed
          ? 'border-emerald-500/40'
          : 'border-zinc-700/30 hover:border-zinc-600/50',
        className
      )}
    >
      {/* Left: Type indicator line */}
      <div className="flex flex-col items-center">
        <div
          className={cn(
            'w-10 h-10 rounded-xl flex items-center justify-center',
            isConfirmed ? 'bg-emerald-500/20' : colors.badge.split(' ')[0]
          )}
        >
          {isConfirmed ? (
            <Check className="w-5 h-5 text-emerald-400" />
          ) : (
            <Icon className={cn('w-5 h-5', colors.icon)} />
          )}
        </div>
      </div>

      {/* Center: Content */}
      <div className="flex-1 min-w-0">
        {/* Header row */}
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <div
            className={cn(
              'flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide border',
              isConfirmed
                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                : colors.badge
            )}
          >
            <Sparkles className="w-3 h-3" />
            {isConfirmed ? 'Confirmed' : 'Suggested'}
          </div>

          {/* Date range for hotels */}
          {suggestionType === 'hotel' && dateRange && (
            <span className="text-xs text-zinc-400">{dateRange}</span>
          )}

          {/* Flight times */}
          {suggestionType === 'flight' && flightTimes && (
            <span className="text-xs font-mono text-zinc-400">
              {flightTimes.departure} → {flightTimes.arrival}
            </span>
          )}
        </div>

        {/* Main content row */}
        <div className="flex gap-3">
          {/* Thumbnail */}
          <div className="relative w-16 h-16 rounded-lg overflow-hidden flex-shrink-0">
            <Image
              src={imageUrl}
              alt={tile.title}
              fill
              className="object-cover"
              sizes="64px"
            />
          </div>

          {/* Details */}
          <div className="flex-1 min-w-0">
            <h4 className="font-semibold text-sm text-zinc-200 line-clamp-1">
              {tile.title}
            </h4>
            {tile.subtitle && (
              <p className="text-xs text-zinc-400 line-clamp-1 mt-0.5">
                {tile.subtitle}
              </p>
            )}

            {/* Price */}
            {tile.price_estimate && (
              <p className="text-sm text-zinc-300 mt-1">
                <span className="font-medium">${tile.price_estimate.toLocaleString()}</span>
                {suggestionType === 'hotel' && (
                  <span className="text-zinc-500">/night</span>
                )}
              </p>
            )}
          </div>
        </div>

        {/* AI reasoning preview (if available) */}
        {typeof tile.meta?.reasoning === 'string' && tile.meta.reasoning && (
          <p className="text-xs text-zinc-500 mt-2 line-clamp-2 italic">
            &ldquo;{tile.meta.reasoning}&rdquo;
          </p>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex flex-col gap-2 flex-shrink-0">
        {!isConfirmed && onConfirmClick && (
          <button
            onClick={onConfirmClick}
            className="flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors"
          >
            <Check className="w-3 h-3" />
            Confirm
          </button>
        )}

        {onChangeClick && (
          <button
            onClick={onChangeClick}
            className={cn(
              'flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              isConfirmed
                ? 'bg-zinc-700/50 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300'
                : 'bg-zinc-700/50 text-zinc-300 hover:bg-zinc-700'
            )}
          >
            <RefreshCw className="w-3 h-3" />
            Change
          </button>
        )}
      </div>
    </div>
  );
}

export default SuggestionBlock;
