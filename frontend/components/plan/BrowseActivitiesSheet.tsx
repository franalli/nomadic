'use client';
/**
 * BrowseActivitiesSheet
 * On-demand activity browser for free/buffer days.
 * Uses stashed Tier-1-suppressed tiles when available; falls back to
 * POST /api/activities/browse (Google Places) otherwise.
 */

import { MapPin, Star } from 'lucide-react';
import Image from 'next/image';
import { useCallback, useEffect, useState } from 'react';

import { BottomSheet } from '@/components/ui/bottom-sheet';
import { browseActivities, type BrowseTile } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

const CATEGORIES = [
  { value: 'all', label: 'All' },
  { value: 'cultural', label: 'Cultural' },
  { value: 'food', label: 'Food' },
  { value: 'nature', label: 'Nature' },
  { value: 'spa', label: 'Spa' },
  { value: 'tours', label: 'Tours' },
  { value: 'shopping', label: 'Shopping' },
];

interface BrowseActivitiesSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  destination: string;
  dayNumber?: number;
  date?: string | null;
  onSelectActivity?: (tile: BrowseTile) => void;
  /** Pre-stashed tiles from logistics_node (skip API call when provided) */
  stashedTiles?: Array<Record<string, unknown>>;
}

export function BrowseActivitiesSheet({
  open,
  onOpenChange,
  destination,
  dayNumber,
  date,
  onSelectActivity,
  stashedTiles,
}: BrowseActivitiesSheetProps) {
  const [tiles, setTiles] = useState<BrowseTile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState('all');

  const fetchTiles = useCallback(async () => {
    if (!destination) return;
    setLoading(true);
    setError(null);
    try {
      const result = await browseActivities({
        destination,
        dayNumber,
        date,
        categories: ['cultural', 'food', 'nature', 'spa', 'tours', 'shopping'],
      });
      setTiles(result.tiles);
    } catch {
      setError('Could not load activities. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [destination, dayNumber, date]);

  // On open: use stashed tiles if available, otherwise fetch from API
  useEffect(() => {
    if (!open) return;
    if (tiles.length > 0 || loading) return;

    if (stashedTiles && stashedTiles.length > 0) {
      // Cast stashed tiles (already in BrowseTile shape from backend _place_to_tile)
      setTiles(stashedTiles as unknown as BrowseTile[]);
    } else {
      fetchTiles();
    }
  }, [open, tiles.length, loading, stashedTiles, fetchTiles]);

  // Reset tiles when destination changes
  useEffect(() => {
    setTiles([]);
  }, [destination]);

  // browse_category is set by logistics_node for stashed tiles (mapped from Places primaryType).
  // activity_browser.py sets category directly. Fall back to category for API-fetched tiles.
  const tileCategory = (t: BrowseTile) =>
    (t as BrowseTile & { browse_category?: string }).browse_category ?? t.category;

  const filteredTiles =
    activeCategory === 'all'
      ? tiles
      : tiles.filter((t) => tileCategory(t) === activeCategory);

  // Only show categories that have at least one tile (always show 'all')
  const visibleCategories = CATEGORIES.filter(
    (cat) => cat.value === 'all' || tiles.some((t) => tileCategory(t) === cat.value)
  );

  return (
    <BottomSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Browse Activities"
      hint={destination}
    >
      {/* Category filter tabs */}
      <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-4 px-4 pb-3">
        {visibleCategories.map((cat) => (
          <button
            key={cat.value}
            type="button"
            onClick={() => setActiveCategory(cat.value)}
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

      {/* Loading skeletons */}
      {loading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="flex gap-3 p-3 rounded-xl bg-zinc-100 dark:bg-zinc-800/50 animate-pulse"
            >
              <div className="w-16 h-16 rounded-lg bg-zinc-200 dark:bg-zinc-700 shrink-0" />
              <div className="flex-1 space-y-2 py-1">
                <div className="h-3 bg-zinc-200 dark:bg-zinc-700 rounded w-3/4" />
                <div className="h-3 bg-zinc-200 dark:bg-zinc-700 rounded w-1/2" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="text-center py-8">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{error}</p>
          <button
            type="button"
            onClick={fetchTiles}
            className="mt-3 text-sm font-medium text-emerald-600 dark:text-emerald-400"
          >
            Try again
          </button>
        </div>
      )}

      {/* Empty state (category filter yields no results) */}
      {!loading && !error && filteredTiles.length === 0 && tiles.length > 0 && (
        <div className="text-center py-8">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No activities in this category</p>
        </div>
      )}

      {/* Activity tiles */}
      {!loading && !error && filteredTiles.length > 0 && (
        <div className="space-y-3">
          {filteredTiles.map((tile) => (
            <button
              key={tile.id}
              type="button"
              onClick={() => onSelectActivity?.(tile)}
              className={cn(
                DS.infoBox.container,
                'w-full text-left transition-all',
                onSelectActivity &&
                  'hover:border-zinc-300 dark:hover:border-white/20 active:scale-[0.99]'
              )}
            >
              <div className="flex gap-3">
                {tile.image_url ? (
                  <div className="relative w-16 h-16 rounded-lg overflow-hidden shrink-0">
                    <Image
                      src={tile.image_url}
                      alt={tile.title}
                      fill
                      className="object-cover"
                      sizes="64px"
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
                  {/* Show subtitle only when it's not just the address repeated */}
                  {tile.subtitle && tile.subtitle !== tile.location_label && (
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-1">
                      {tile.subtitle}
                    </p>
                  )}
                  <div className="flex items-center gap-2 mt-1">
                    {tile.rating != null && (
                      <span className="flex items-center gap-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                        <Star className="w-3 h-3 fill-current text-amber-400" />
                        {tile.rating.toFixed(1)}
                        {tile.review_count != null && (
                          <span className="ml-0.5">({tile.review_count.toLocaleString()})</span>
                        )}
                      </span>
                    )}
                    {tile.price_estimate && (
                      <span className="text-xs text-zinc-500 dark:text-zinc-400">
                        {tile.price_estimate}
                      </span>
                    )}
                    {tile.location_label && (
                      <span className="text-xs text-zinc-400 dark:text-zinc-500 truncate">
                        {tile.location_label}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </BottomSheet>
  );
}
