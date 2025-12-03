'use client';

import { useEffect, useRef, useState } from 'react';

import { apiFetch } from '@/lib/api';
import type { DocumentBranch, PlanDocumentResponse } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

import { selectionsToTileSelection } from './useTileSelection';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Document structure returned from the session hydration API.
 * Contains all data needed to restore a previous planning session.
 */
export interface SessionDocument {
  /** Unique identifier for the trip context (may be undefined for new sessions) */
  trip_context_id?: number | null;
  /** All branches (trip suggestions) for this session */
  branches: DocumentBranch[];
  /** Map of tile IDs to tile objects */
  tiles: Record<string, Tile>;
}

/**
 * Options for the useSessionHydration hook.
 */
export interface UseSessionHydrationOptions {
  /**
   * Function to fetch the session document from the store.
   * Should return the cached document or fetch from API.
   */
  fetchDocument: () => Promise<SessionDocument | null>;

  /**
   * Setter for branch state.
   * Called when session is restored with saved branches.
   */
  setBranches: React.Dispatch<React.SetStateAction<DocumentBranch[]>>;

  /**
   * Setter for tiles map state.
   * Called when session is restored with saved tiles.
   */
  setTilesMap: React.Dispatch<React.SetStateAction<Record<string, Tile>>>;

  /**
   * Setter for branch selections state.
   * Called when session is restored with saved selections.
   */
  setBranchSelections: React.Dispatch<React.SetStateAction<Record<string, TileSelection>>>;

  /**
   * Setter for selected branch ID.
   * Called to restore the previously selected branch.
   */
  setSelectedBranchId: React.Dispatch<React.SetStateAction<string | null>>;

  /**
   * Setter for tiles branch ID.
   * Called to indicate which branch's tiles are currently loaded.
   */
  setTilesBranchId: React.Dispatch<React.SetStateAction<string | null>>;

  /**
   * Toast notification callback for error messages.
   */
  onToast: (message: string) => void;
}

/**
 * Return type for the useSessionHydration hook.
 */
export interface UseSessionHydrationReturn {
  /**
   * Whether the session is currently being restored from storage/API.
   * True during initial mount while fetching saved session data.
   * UI can show a loading state while this is true.
   */
  isHydratingSnapshot: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Hook for restoring a planning session from storage on mount.
 *
 * Handles:
 * - Fetching saved session document on component mount
 * - Restoring branches, tiles, and selections
 * - Auto-selecting the primary branch
 * - Fetching tiles if the saved branch doesn't have them
 * - Error handling with user-friendly toasts
 *
 * This hook runs once on mount and populates the branch manager state
 * from the previously saved session. This allows users to continue
 * planning where they left off after refreshing the page.
 *
 * @param options - Configuration options for the hook
 * @returns Hydration state
 *
 * @remarks
 * The hydration process:
 * 1. Fetches document from documentStore (cached or API)
 * 2. If document exists with branches, restores all state
 * 3. Converts server-side ID selections to tile objects
 * 4. Selects the primary branch (or first branch as fallback)
 * 5. If primary branch lacks tiles, fetches them from API
 *
 * TODO: Consider adding retry logic for failed hydration.
 * TODO: Consider adding a "session expired" flow for stale sessions.
 *
 * @example
 * ```tsx
 * const { isHydratingSnapshot } = useSessionHydration({
 *   fetchDocument: documentStore.fetchDocument,
 *   setBranches,
 *   setTilesMap,
 *   setBranchSelections,
 *   setSelectedBranchId,
 *   setTilesBranchId,
 *   onToast,
 * });
 *
 * if (isHydratingSnapshot) {
 *   return <LoadingSpinner />;
 * }
 * ```
 */
export function useSessionHydration(options: UseSessionHydrationOptions): UseSessionHydrationReturn {
  const {
    fetchDocument,
    setBranches,
    setTilesMap,
    setBranchSelections,
    setSelectedBranchId,
    setTilesBranchId,
    onToast,
  } = options;

  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(true);

  /**
   * Ref to track abort controller for tile fetches during hydration.
   * Used to cancel in-flight requests if component unmounts.
   */
  const tilesFetchControllerRef = useRef<AbortController | null>(null);

  // Hydrate session document on mount
  useEffect(() => {
    let cancelled = false;

    async function hydrateSessionDocument() {
      try {
        setIsHydratingSnapshot(true);

        // Fetch document from store (handles caching internally)
        const doc = await fetchDocument();
        if (cancelled) return;

        // No document or no branches - nothing to restore
        if (!doc || !doc.branches.length) return;

        // Restore core state from document
        setBranches(doc.branches);
        setTilesMap(doc.tiles);

        // Convert server-side ID selections to tile object selections
        const restoredSelections: Record<string, TileSelection> = {};
        for (const branch of doc.branches) {
          restoredSelections[branch.id] = selectionsToTileSelection(branch.selections, doc.tiles);
        }
        setBranchSelections(restoredSelections);

        // Determine which branch to select
        // Prefer primary branch, fall back to first branch
        const primaryBranch = doc.branches.find((b) => b.is_primary);
        const fallbackBranchId = primaryBranch?.id ?? doc.branches[0].id;

        setSelectedBranchId(fallbackBranchId);
        setTilesBranchId(fallbackBranchId);

        // Check if the selected branch already has tiles loaded
        const hasTilesForBranch =
          primaryBranch &&
          (primaryBranch.tiles.stays.length > 0 ||
            primaryBranch.tiles.flights.length > 0 ||
            primaryBranch.tiles.activities.length > 0);

        // If no tiles, fetch them from the API
        if (!hasTilesForBranch && fallbackBranchId) {
          const controller = new AbortController();
          tilesFetchControllerRef.current = controller;

          setTilesBranchId(null); // Mark as loading

          try {
            const res = await apiFetch(
              `/v1/document/tiles/${encodeURIComponent(fallbackBranchId)}`,
              {
                method: 'POST',
                signal: controller.signal,
              }
            );

            if (!res.ok) {
              console.error('Failed to fetch tiles during hydration', res.status);
              onToast(
                'We restored your suggestions but could not refresh options automatically. Select a suggestion to try again.'
              );
              return;
            }

            const data: PlanDocumentResponse = await res.json();
            if (controller.signal.aborted) return;

            // Update state with fetched tiles
            setBranches(data.document.branches);
            setTilesMap(data.document.tiles);
            setTilesBranchId(fallbackBranchId);
          } catch (error) {
            if ((error as DOMException).name === 'AbortError') return;
            console.error('Failed to fetch tiles during hydration', error);
            onToast(
              'We restored your suggestions but could not refresh options automatically. Select a suggestion to try again.'
            );
          } finally {
            if (tilesFetchControllerRef.current === controller) {
              tilesFetchControllerRef.current = null;
            }
          }
        }
      } catch (error) {
        console.error('Failed to hydrate session document', error);
        onToast('Unable to reload your previous session. You can still plan a new trip.');
      } finally {
        if (!cancelled) {
          setIsHydratingSnapshot(false);
        }
      }
    }

    hydrateSessionDocument();

    // Cleanup: cancel any in-flight requests and mark as cancelled
    return () => {
      cancelled = true;
      if (tilesFetchControllerRef.current) {
        tilesFetchControllerRef.current.abort();
        tilesFetchControllerRef.current = null;
      }
    };
    // Intentionally run only on mount to restore session once
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    isHydratingSnapshot,
  };
}
