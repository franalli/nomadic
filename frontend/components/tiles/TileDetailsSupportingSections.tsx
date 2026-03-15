'use client';

import { ChevronLeft, ChevronRight, MapPin } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type { PartnerPrice, Tile } from '@/types/tile';

import { getTileActivityMeta } from './tileHelpers';

type TileDetailsImageCarouselProps = {
  images: string[];
  title?: string;
};

export function TileDetailsImageCarousel({ images, title }: TileDetailsImageCarouselProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const goToPrevious = useCallback(() => {
    setCurrentIndex((prev) => (prev === 0 ? images.length - 1 : prev - 1));
  }, [images.length]);
  const goToNext = useCallback(() => {
    setCurrentIndex((prev) => (prev === images.length - 1 ? 0 : prev + 1));
  }, [images.length]);

  if (images.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center bg-gradient-to-br from-zinc-200 to-zinc-300 dark:from-zinc-700 dark:to-zinc-800">
        <MapPin className="h-12 w-12 text-zinc-500 dark:text-zinc-400" />
      </div>
    );
  }

  return (
    <div className="relative h-64 overflow-hidden bg-zinc-100 dark:bg-zinc-800">
      <img src={images[currentIndex]} alt={title ?? ''} loading="lazy" className="h-full w-full object-cover" />
      {images.length > 1 && (
        <>
          <button
            type="button"
            onClick={goToPrevious}
            aria-label="Previous image"
            className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white transition-colors hover:bg-black/70"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={goToNext}
            aria-label="Next image"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white transition-colors hover:bg-black/70"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
          <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-1.5">
            {images.map((_, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setCurrentIndex(idx)}
                aria-label={`Go to image ${idx + 1}`}
                className={cn('h-2 w-2 rounded-full transition-colors', idx === currentIndex ? 'bg-white' : 'bg-white/50')}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

type TileDetailsActivitySectionProps = {
  tile: Tile;
};

export function TileDetailsActivitySection({ tile }: TileDetailsActivitySectionProps) {
  const meta = useMemo(() => getTileActivityMeta(tile), [tile]);
  const skillLevel = useMemo(() => {
    const rawMeta = tile.meta as Record<string, unknown> | undefined;
    return typeof rawMeta?.skill_level === 'string' && rawMeta.skill_level !== 'beginner'
      ? rawMeta.skill_level
      : null;
  }, [tile]);

  if (!meta) return null;

  return (
    <div className="space-y-2">
      {meta.description && (
        <p className="text-sm italic text-zinc-500 dark:text-zinc-400">{meta.description}</p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {meta.category && (
          <span className="rounded bg-zinc-100 px-2 py-1 text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {meta.category}
          </span>
        )}
        {meta.durationHours != null && (
          <span className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {meta.durationHours}h
          </span>
        )}
        {meta.timeOfDay && (
          <span className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {meta.timeOfDay.charAt(0).toUpperCase() + meta.timeOfDay.slice(1)}
          </span>
        )}
        {skillLevel && (
          <span className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {skillLevel.charAt(0).toUpperCase() + skillLevel.slice(1)}
          </span>
        )}
      </div>
    </div>
  );
}

type TileDetailsPartnerPricesProps = {
  tile: Tile;
  partnerPrices?: PartnerPrice[];
  onBook?: (tile: Tile, partner: string) => void;
};

export function TileDetailsPartnerPrices({
  tile,
  partnerPrices,
  onBook,
}: TileDetailsPartnerPricesProps) {
  if (!partnerPrices?.length) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Compare prices</h3>
      <div className="space-y-2">
        {partnerPrices.map((pp) => (
          <div
            key={pp.partner}
            className={cn(
              'flex items-center justify-between rounded-lg border p-3 transition-colors',
              pp.isBestPrice
                ? 'border-emerald-500/50 bg-emerald-500/10'
                : 'border-zinc-200 bg-zinc-100 hover:bg-zinc-100 dark:border-white/10 dark:bg-zinc-800/30 dark:hover:bg-zinc-800/50'
            )}
          >
            <div className="flex items-center gap-2">
              {pp.logo ? (
                <img src={pp.logo} alt={pp.partner} loading="lazy" className="h-6 w-auto object-contain" />
              ) : (
                <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  {pp.partner}
                </span>
              )}
              {pp.isBestPrice && (
                <span className={`px-1.5 py-0.5 rounded ${DS.textSize.micro} font-medium bg-emerald-500/20 text-emerald-400`}>
                  Best Price
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {new Intl.NumberFormat('en-US', {
                  style: 'currency',
                  currency: pp.currency,
                  maximumFractionDigits: 0,
                }).format(pp.price)}
              </span>
              <button
                type="button"
                onClick={() => {
                  if (pp.url) {
                    window.open(pp.url, '_blank', 'noopener,noreferrer');
                  }
                  onBook?.(tile, pp.partner);
                }}
                className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-600"
              >
                Book
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
