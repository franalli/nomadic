'use client';
/**
 * BrowseActivitiesSheet
 * On-demand activity browser for free/buffer days.
 * Uses stashed Tier-1-suppressed tiles when available; falls back to
 * POST /api/activities/browse (Google Places) otherwise.
 */

import { useCallback, useEffect, useState } from 'react';

import { BottomSheet } from '@/components/ui/bottom-sheet';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { type BrowseTile } from '@/lib/api';
import { browseActivities } from '@/lib/api-streaming';
import { getSignedGooglePlacesPhotoProxyUrl } from '@/lib/googlePlacesPhoto';

import {
  BrowseErrorState,
  BrowseLoadingSkeleton,
  BrowseTileCard,
  CATEGORIES,
  CategoryFilter,
  tileCategory,
} from './BrowseActivitiesContent';

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
  const [signedImageByTileId, setSignedImageByTileId] = useState<Record<string, string>>({});
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
        categories: ['cultural'],
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
      setTiles(stashedTiles as unknown as BrowseTile[]);
    } else {
      fetchTiles();
    }
  }, [open, tiles.length, loading, stashedTiles, fetchTiles]);

  // Reset tiles when destination changes
  useEffect(() => {
    setTiles([]);
    setSignedImageByTileId({});
  }, [destination]);

  useEffect(() => {
    let cancelled = false;
    const candidates = tiles.filter((tile) => Boolean(tile.photo_name));
    if (candidates.length === 0) return () => {
      cancelled = true;
    };

    Promise.all(
      candidates.map(async (tile) => {
        const signed = await getSignedGooglePlacesPhotoProxyUrl(tile.photo_name, {
          maxWidth: 256,
          maxHeight: 256,
        });
        return { tileId: tile.id, signed };
      })
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<string, string> = {};
      for (const entry of entries) {
        if (entry.signed) next[entry.tileId] = entry.signed;
      }
      if (Object.keys(next).length === 0) return;
      setSignedImageByTileId((prev) => ({ ...prev, ...next }));
    }).catch((err) => {
      if (!cancelled) console.error('[BrowseActivitiesSheet] photo signing failed:', err);
    });

    return () => {
      cancelled = true;
    };
  }, [tiles]);

  const filteredTiles =
    activeCategory === 'all'
      ? tiles
      : tiles.filter((t) => tileCategory(t) === activeCategory);

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
      <ErrorBoundary label="Browse activities">
      <CategoryFilter
        categories={visibleCategories}
        activeCategory={activeCategory}
        onSelect={setActiveCategory}
      />

      {loading && <BrowseLoadingSkeleton />}

      {error && !loading && (
        <BrowseErrorState error={error} onRetry={fetchTiles} />
      )}

      {!loading && !error && filteredTiles.length === 0 && tiles.length > 0 && (
        <div className="text-center py-8">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">No activities in this category</p>
        </div>
      )}

      {!loading && !error && filteredTiles.length > 0 && (
        <div className="space-y-4">
          {filteredTiles.map((tile) => (
            <BrowseTileCard
              key={tile.id}
              tile={tile}
              imageSrc={signedImageByTileId[tile.id] || tile.image_url}
              onSelect={onSelectActivity}
            />
          ))}
        </div>
      )}
      </ErrorBoundary>
    </BottomSheet>
  );
}
