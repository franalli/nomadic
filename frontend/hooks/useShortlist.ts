/**
 * useShortlist
 *
 * Hook for managing the user's shortlist of saved tiles in S2.
 * Tracks saved items by category with primary stay selection.
 *
 * Now integrates with documentStore.preferredTileIds for persistence.
 * Local state tracks category and isPrimary; IDs sync to backend.
 *
 * Rules:
 * - Stays: pick 1 primary (required to proceed)
 * - Flights: 0-1 (optional)
 * - Activities: 0-3 (optional)
 */

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { useDocumentStore } from '@/state/documentStore';
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
export function getCategoryFromTile(tile: Tile): ShortlistCategory {
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

// Stable empty object for when no tiles exist (avoids new object on each render)
const EMPTY_TILES: Record<string, Tile> = {};

export function useShortlist(): UseShortlistReturn {
  // Connect to documentStore for persistence
  // Use stable selectors to avoid infinite re-render loops
  const preferredTileIds = useDocumentStore((state) => state.preferredTileIds);
  const tiles = useDocumentStore((state) => state.document?.tiles ?? EMPTY_TILES);

  // Get actions from store directly (stable references, not via selector that creates new objects)
  const toggleTilePreference = useDocumentStore((state) => state.toggleTilePreference);
  const clearPreferences = useDocumentStore((state) => state.clearPreferences);

  // Local state for category and isPrimary (computed/UI-specific, not persisted)
  const [itemsMetadata, setItemsMetadata] = useState<Map<string, { category: ShortlistCategory; isPrimary: boolean }>>(
    new Map()
  );

  // Sync itemsMetadata when preferredTileIds changes (e.g., on hydration)
  useEffect(() => {
    setItemsMetadata((prev) => {
      const newMap = new Map(prev);
      let changed = false;

      // Add metadata for new IDs (from hydration)
      for (const tileId of preferredTileIds) {
        if (!newMap.has(tileId)) {
          const tile = tiles[tileId];
          if (tile) {
            const category = getCategoryFromTile(tile);
            // First stay becomes primary
            const staysInMap = Array.from(newMap.values()).filter((m) => m.category === 'stays');
            const isPrimary = category === 'stays' && staysInMap.length === 0;
            newMap.set(tileId, { category, isPrimary });
            changed = true;
          }
        }
      }

      // Remove metadata for IDs no longer in preferences
      for (const tileId of newMap.keys()) {
        if (!preferredTileIds.has(tileId)) {
          newMap.delete(tileId);
          changed = true;
        }
      }

      return changed ? newMap : prev;
    });
  }, [preferredTileIds, tiles]);

  // Build items array from preferredTileIds + metadata
  const items = useMemo((): ShortlistItem[] => {
    const result: ShortlistItem[] = [];
    for (const tileId of preferredTileIds) {
      const meta = itemsMetadata.get(tileId);
      if (meta) {
        result.push({ tileId, category: meta.category, isPrimary: meta.isPrimary });
      } else {
        // Tile not in metadata yet (loading), derive category from tiles map
        const tile = tiles[tileId];
        if (tile) {
          result.push({ tileId, category: getCategoryFromTile(tile), isPrimary: false });
        }
      }
    }
    return result;
  }, [preferredTileIds, itemsMetadata, tiles]);

  // Computed values
  const savedTileIds = preferredTileIds; // Now backed by documentStore

  const counts = useMemo(() => {
    return {
      stays: items.filter((i) => i.category === 'stays').length,
      flights: items.filter((i) => i.category === 'flights').length,
      activities: items.filter((i) => i.category === 'activities').length,
    };
  }, [items]);

  const primaryStayId = useMemo(() => {
    const primaryStay = items.find((i) => i.category === 'stays' && i.isPrimary);
    return primaryStay?.tileId ?? null;
  }, [items]);

  const hasPrimaryStay = primaryStayId !== null;
  const canProceed = hasPrimaryStay;

  // Add item to shortlist (persists to backend via documentStore)
  const addItem = useCallback(
    (tile: Tile) => {
      const category = getCategoryFromTile(tile);

      // Check if already saved
      if (preferredTileIds.has(tile.id)) {
        return;
      }

      // Check category limit - may need to remove oldest
      const currentCategoryCount = items.filter((i) => i.category === category).length;
      if (currentCategoryCount >= CATEGORY_LIMITS[category]) {
        // Find oldest non-primary item in category to replace
        const toRemove = items.find((i) => i.category === category && !i.isPrimary);
        if (toRemove) {
          // Remove old item from preferences
          toggleTilePreference(toRemove.tileId);
        } else {
          // Can't add - all slots are primary or at limit
          return;
        }
      }

      // For stays: if this is the first one, make it primary automatically
      const isFirstStay = category === 'stays' && !items.some((i) => i.category === 'stays');

      // Update local metadata
      setItemsMetadata((prev) => {
        const newMap = new Map(prev);
        newMap.set(tile.id, { category, isPrimary: isFirstStay });
        return newMap;
      });

      // Persist to backend
      toggleTilePreference(tile.id);
    },
    [preferredTileIds, items, toggleTilePreference]
  );

  // Remove item from shortlist (persists to backend via documentStore)
  const removeItem = useCallback(
    (tileId: string) => {
      const item = items.find((i) => i.tileId === tileId);
      if (!item) return;

      // If removing primary stay, promote next stay to primary
      if (item.category === 'stays' && item.isPrimary) {
        const nextStay = items.find((i) => i.category === 'stays' && i.tileId !== tileId);
        if (nextStay) {
          setItemsMetadata((prev) => {
            const newMap = new Map(prev);
            const meta = newMap.get(nextStay.tileId);
            if (meta) {
              newMap.set(nextStay.tileId, { ...meta, isPrimary: true });
            }
            return newMap;
          });
        }
      }

      // Remove from local metadata
      setItemsMetadata((prev) => {
        const newMap = new Map(prev);
        newMap.delete(tileId);
        return newMap;
      });

      // Persist to backend
      toggleTilePreference(tileId);
    },
    [items, toggleTilePreference]
  );

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
    setItemsMetadata((prev) => {
      const meta = prev.get(tileId);
      if (!meta || meta.category !== 'stays') return prev;

      const newMap = new Map(prev);
      // Set all stays to non-primary, then set this one to primary
      for (const [id, m] of newMap) {
        if (m.category === 'stays') {
          newMap.set(id, { ...m, isPrimary: id === tileId });
        }
      }
      return newMap;
    });
  }, []);

  // Clear entire shortlist (persists to backend via documentStore)
  const clear = useCallback(() => {
    setItemsMetadata(new Map());
    clearPreferences();
  }, [clearPreferences]);

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
