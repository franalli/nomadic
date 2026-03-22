'use client';

import {
  ArrowDown,
  ArrowUp,
  Check,
  Minus,
  Star,
} from 'lucide-react';
import Image from 'next/image';
import { memo, useCallback, useState } from 'react';

import { DS } from '@/lib/design-system';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { Tile } from '@/types/tile';

import { formatPriceOrDash, getPriceDiff, getRatingDiff } from './alternativesHelpers';

// ─────────────────────────────────────────────────────────────────────────────
// TileThumbnail
// ─────────────────────────────────────────────────────────────────────────────

export const TileThumbnail = memo(function TileThumbnail({
  tile,
  size,
}: {
  tile: Tile;
  size: string;
}) {
  const [hasError, setHasError] = useState(false);
  const handleError = useCallback(() => setHasError(true), []);

  const placeholderUrl = placeholderImageForTile(tile);
  const imageSrc = hasError ? placeholderUrl : (tile.image_url || placeholderUrl);

  return (
    <Image
      src={imageSrc}
      alt={tile.title}
      fill
      className="object-cover"
      sizes={size}
      onError={handleError}
    />
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// CurrentSelectionCard
// ─────────────────────────────────────────────────────────────────────────────

interface CurrentSelectionCardProps {
  tile: Tile;
}

export function CurrentSelectionCard({ tile }: CurrentSelectionCardProps) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 dark:text-zinc-400 uppercase tracking-wide font-medium">
        Current Selection
      </p>
      <div className="flex gap-4 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
        <div className="relative w-16 h-16 rounded-lg overflow-hidden flex-shrink-0">
          <TileThumbnail tile={tile} size="64px" />
          <div className="absolute inset-0 flex items-center justify-center bg-emerald-500/40">
            <Check className="w-6 h-6 text-white" />
          </div>
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="font-semibold text-sm text-zinc-800 dark:text-zinc-200 line-clamp-1">
            {tile.title}
          </h4>
          <div className="flex items-center gap-2 mt-1">
            {tile.rating && (
              <div className="flex items-center gap-0.5">
                <Star className="w-3 h-3 text-zinc-500 dark:text-zinc-300 fill-current" />
                <span className="text-xs text-zinc-700 dark:text-zinc-300">
                  {tile.rating.toFixed(1)}
                </span>
              </div>
            )}
            {tile.price_estimate && (
              <span className="text-xs font-medium text-emerald-400">
                {formatPriceOrDash(tile.price_estimate)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// AlternativeCard
// ─────────────────────────────────────────────────────────────────────────────

interface AlternativeCardProps {
  alt: Tile;
  currentPrice: number | undefined;
  currentRating: number | undefined;
  isCurrentlySelected: boolean;
  onSelect: (tile: Tile) => void;
}

export function AlternativeCard({
  alt,
  currentPrice,
  currentRating,
  isCurrentlySelected,
  onSelect,
}: AlternativeCardProps) {
  const priceDiff = getPriceDiff(currentPrice, alt.price_estimate);
  const ratingDiff = getRatingDiff(currentRating, alt.rating);

  return (
    <button
      onClick={() => !isCurrentlySelected && onSelect(alt)}
      disabled={isCurrentlySelected}
      className={cn(
        'w-full flex gap-4 p-3 rounded-xl text-left transition-colors',
        isCurrentlySelected
          ? 'bg-zinc-50 dark:bg-zinc-800/30 opacity-50 cursor-not-allowed'
          : 'bg-zinc-100 dark:bg-zinc-800/50 hover:bg-zinc-200 dark:hover:bg-zinc-700/50 border border-zinc-200 dark:border-white/10 hover:border-zinc-300 dark:hover:border-zinc-600/50'
      )}
    >
      <div className="relative w-14 h-14 rounded-lg overflow-hidden flex-shrink-0">
        <TileThumbnail tile={alt} size="56px" />
      </div>
      <div className="flex-1 min-w-0">
        <h4 className="font-medium text-sm text-zinc-800 dark:text-zinc-200 line-clamp-1">
          {alt.title}
        </h4>
        <div className="flex items-center gap-2 mt-1">
          {alt.rating && (
            <div className="flex items-center gap-0.5">
              <Star className="w-3 h-3 text-zinc-500 dark:text-zinc-400 fill-current" />
              <span className="text-xs text-zinc-700 dark:text-zinc-300">
                {alt.rating.toFixed(1)}
              </span>
            </div>
          )}
          {ratingDiff && ratingDiff.type !== 'same' && (
            <span
              className={cn(
                `flex items-center gap-0.5 ${DS.textSize.micro} font-medium px-1 py-0.5 rounded`,
                ratingDiff.type === 'better'
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-zinc-200 text-zinc-700 dark:bg-zinc-700/50 dark:text-zinc-300'
              )}
            >
              {ratingDiff.type === 'better' ? (
                <ArrowUp className="w-2.5 h-2.5" />
              ) : (
                <ArrowDown className="w-2.5 h-2.5" />
              )}
              {ratingDiff.label}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
            {formatPriceOrDash(alt.price_estimate)}
          </span>
          {priceDiff && priceDiff.type !== 'same' && (
            <span
              className={cn(
                `flex items-center gap-0.5 ${DS.textSize.micro} font-medium px-1 py-0.5 rounded`,
                priceDiff.type === 'cheaper'
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-rose-500/20 text-rose-400'
              )}
            >
              {priceDiff.type === 'cheaper' ? (
                <Minus className="w-2.5 h-2.5" />
              ) : null}
              {priceDiff.label}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}
