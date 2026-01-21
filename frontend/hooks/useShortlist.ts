/**
 * useShortlist
 *
 * Hook for managing the user's shortlist of saved tiles in S2.
 * Tracks saved items by category with primary stay selection.
 *
 * Rules:
 * - Stays: pick 1 primary (required to proceed)
 * - Flights: 0-1 (optional)
 * - Activities: 0-3 (optional)
 */

'use client';

import { useCallback, useMemo, useState } from 'react';

import type { Tile } from '@/types/tile';

export type ShortlistCategory = 'stays' | 'flights' | 'activities';

export interface ShortlistItem {
  tileId: string;
  category: ShortlistCategory;
  isPrimary?: boolean;
}

export interface UseShortlistReturn {
  /** All shortlisted items */
  items: ShortlistItem[];
  /** Set of tile IDs for quick lookup */
  savedTileIds: Set<string>;
  /** Add a tile to shortlist */
  addItem: (tile: Tile) => void;
  /** Remove a tile from shortlist */
  removeItem: (tileId: string) => void;
  /** Toggle a tile (add if not saved, remove if saved) */
  toggleItem: (tile: Tile) => void;
  /** Set a stay as primary */
  setPrimary: (tileId: string) => void;
  /** Whether a primary stay has been selected */
  hasPrimaryStay: boolean;
  /** Primary stay tile ID (if any) */
  primaryStayId: string | null;
  /** Counts by category */
  counts: { stays: number; flights: number; activities: number };
  /** Check if shortlist is ready to proceed (has primary stay) */
  canProceed: boolean;
  /** Clear entire shortlist */
  clear: () => void;
}

/**
 * Determine category from tile type
 */
function getCategoryFromTile(tile: Tile): ShortlistCategory {
  const type = tile.type?.toLowerCase() || '';

  if (type === 'hotel' || type === 'stay' || type === 'accommodation') {
    return 'stays';
  }
  if (type === 'flight') {
    return 'flights';
  }
  // Default to activities for tours, experiences, attractions, etc.
  return 'activities';
}

/**
 * Category limits
 */
const CATEGORY_LIMITS: Record<ShortlistCategory, number> = {
  stays: 3, // Can save multiple but must pick 1 primary
  flights: 1,
  activities: 3,
};

export function useShortlist(): UseShortlistReturn {
  const [items, setItems] = useState<ShortlistItem[]>([]);

  // Computed values
  const savedTileIds = useMemo(() => {
    return new Set(items.map((item) => item.tileId));
  }, [items]);

  const counts = useMemo(() => {
    return {
      stays: items.filter((i) => i.category === 'stays').length,
      flights: items.filter((i) => i.category === 'flights').length,
      activities: items.filter((i) => i.category === 'activities').length,
    };
  }, [items]);

  const primaryStayId = useMemo(() => {
    const primaryStay = items.find(
      (i) => i.category === 'stays' && i.isPrimary
    );
    return primaryStay?.tileId ?? null;
  }, [items]);

  const hasPrimaryStay = primaryStayId !== null;
  const canProceed = hasPrimaryStay;

  // Add item to shortlist
  const addItem = useCallback((tile: Tile) => {
    const category = getCategoryFromTile(tile);

    setItems((prev) => {
      // Check if already saved
      if (prev.some((i) => i.tileId === tile.id)) {
        return prev;
      }

      // Check category limit
      const categoryCount = prev.filter((i) => i.category === category).length;
      if (categoryCount >= CATEGORY_LIMITS[category]) {
        // Replace oldest in category (except primary for stays)
        const toRemove = prev.find(
          (i) => i.category === category && !i.isPrimary
        );
        if (toRemove) {
          const filtered = prev.filter((i) => i.tileId !== toRemove.tileId);
          return [...filtered, { tileId: tile.id, category }];
        }
        // Can't add - all slots are primary or at limit
        return prev;
      }

      // For stays: if this is the first one, make it primary automatically
      const isFirstStay =
        category === 'stays' && !prev.some((i) => i.category === 'stays');

      return [
        ...prev,
        {
          tileId: tile.id,
          category,
          isPrimary: isFirstStay,
        },
      ];
    });
  }, []);

  // Remove item from shortlist
  const removeItem = useCallback((tileId: string) => {
    setItems((prev) => {
      const item = prev.find((i) => i.tileId === tileId);
      if (!item) return prev;

      const filtered = prev.filter((i) => i.tileId !== tileId);

      // If removed primary stay, promote next stay to primary
      if (item.category === 'stays' && item.isPrimary) {
        const nextStay = filtered.find((i) => i.category === 'stays');
        if (nextStay) {
          return filtered.map((i) =>
            i.tileId === nextStay.tileId ? { ...i, isPrimary: true } : i
          );
        }
      }

      return filtered;
    });
  }, []);

  // Toggle item (add or remove)
  const toggleItem = useCallback(
    (tile: Tile) => {
      if (savedTileIds.has(tile.id)) {
        removeItem(tile.id);
      } else {
        addItem(tile);
      }
    },
    [savedTileIds, addItem, removeItem]
  );

  // Set a stay as primary
  const setPrimary = useCallback((tileId: string) => {
    setItems((prev) => {
      const item = prev.find((i) => i.tileId === tileId);
      if (!item || item.category !== 'stays') return prev;

      return prev.map((i) => ({
        ...i,
        isPrimary: i.category === 'stays' ? i.tileId === tileId : i.isPrimary,
      }));
    });
  }, []);

  // Clear entire shortlist
  const clear = useCallback(() => {
    setItems([]);
  }, []);

  return {
    items,
    savedTileIds,
    addItem,
    removeItem,
    toggleItem,
    setPrimary,
    hasPrimaryStay,
    primaryStayId,
    counts,
    canProceed,
    clear,
  };
}

export default useShortlist;
