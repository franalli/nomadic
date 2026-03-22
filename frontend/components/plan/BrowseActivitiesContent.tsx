import { MapPin, Star } from 'lucide-react';
import Image from 'next/image';

import { type BrowseTile } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { isGooglePlacesPhotoProxyUrl } from '@/lib/googlePlacesPhoto';
import { cn } from '@/lib/utils';

export const CATEGORIES = [
  { value: 'all', label: 'All' },
  { value: 'cultural', label: 'Cultural' },
  { value: 'food', label: 'Food' },
  { value: 'nature', label: 'Nature' },
  { value: 'spa', label: 'Spa' },
  { value: 'shopping', label: 'Shopping' },
];

/** Resolve browse_category (stashed) or category (API-fetched) */
export function tileCategory(t: BrowseTile): string | undefined {
  return (t as BrowseTile & { browse_category?: string }).browse_category ?? t.category;
}

interface CategoryFilterProps {
  categories: typeof CATEGORIES;
  activeCategory: string;
  onSelect: (value: string) => void;
}

export function CategoryFilter({ categories, activeCategory, onSelect }: CategoryFilterProps) {
  return (
    <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 pb-3">
      {categories.map((cat) => (
        <button
          key={cat.value}
          type="button"
          onClick={() => onSelect(cat.value)}
          className={cn(
            'shrink-0',
            DS.pills.shapeFull,
            activeCategory === cat.value ? DS.pills.active : DS.pills.inactive
          )}
        >
          {cat.label}
        </button>
      ))}
    </div>
  );
}

export function BrowseLoadingSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div
          key={`skeleton-item-${i}`}
          className="flex gap-4 p-3 rounded-xl bg-zinc-100 dark:bg-zinc-800/50 animate-pulse"
        >
          <div className="w-16 h-16 rounded-lg bg-zinc-200/50 dark:bg-zinc-700/50 shrink-0" />
          <div className="flex-1 space-y-2 py-1">
            <div className="h-3 bg-zinc-200/50 dark:bg-zinc-700/50 rounded w-3/4" />
            <div className="h-3 bg-zinc-200/50 dark:bg-zinc-700/50 rounded w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

interface BrowseErrorStateProps {
  error: string;
  onRetry: () => void;
}

export function BrowseErrorState({ error, onRetry }: BrowseErrorStateProps) {
  return (
    <div className="text-center py-8">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">{error}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 text-sm font-medium text-emerald-600 dark:text-emerald-400"
      >
        Try again
      </button>
    </div>
  );
}

interface BrowseTileCardProps {
  tile: BrowseTile;
  imageSrc: string | null | undefined;
  onSelect?: (tile: BrowseTile) => void;
}

export function BrowseTileCard({ tile, imageSrc, onSelect }: BrowseTileCardProps) {
  return (
    <button
      key={tile.id}
      type="button"
      onClick={() => onSelect?.(tile)}
      className={cn(
        DS.infoBox.container,
        'w-full text-left transition-all overflow-hidden',
        onSelect &&
          'hover:border-zinc-300 dark:hover:border-white/20 active:scale-[0.99]'
      )}
    >
      <div className="flex gap-4">
        {imageSrc ? (
          <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0">
            <Image
              src={imageSrc}
              alt={tile.title}
              fill
              className="object-cover"
              sizes="64px"
              unoptimized={isGooglePlacesPhotoProxyUrl(imageSrc) || imageSrc.startsWith('/')}
            />
          </div>
        ) : (
          <div className="w-16 h-16 rounded-lg bg-zinc-100 dark:bg-zinc-800 shrink-0 flex items-center justify-center">
            <MapPin className="w-5 h-5 text-zinc-400" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <p className="font-medium text-sm text-zinc-900 dark:text-zinc-100 line-clamp-1">
            {tile.title}
          </p>
          {tile.subtitle && tile.subtitle !== tile.location_label && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-1">
              {tile.subtitle}
            </p>
          )}
          <div className="flex items-center gap-2 mt-1 flex-wrap min-w-0">
            {tile.rating != null && (
              <span className="flex items-center gap-0.5 text-xs text-zinc-500 dark:text-zinc-400 min-w-0">
                <Star className="w-3 h-3 fill-current text-amber-400" />
                {tile.rating.toFixed(1)}
                {tile.review_count != null && (
                  <span className="ml-0.5">({tile.review_count.toLocaleString()})</span>
                )}
              </span>
            )}
            {tile.price_estimate && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400 min-w-0">
                {tile.price_estimate}
              </span>
            )}
            {tile.duration && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400 min-w-0">
                {tile.duration}
              </span>
            )}
            {tile.location_label && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400 min-w-0 truncate flex-1">
                {tile.location_label}
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}
