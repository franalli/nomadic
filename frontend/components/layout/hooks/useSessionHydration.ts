'use client';

import { useEffect, useRef, useState } from 'react';

import { fetchWithRetry } from '@/lib/api';
import type { DocumentBranch, PlanDocumentResponse } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

import { selectionsToTileSelection } from './useTileSelection';

// ─────────────────────────────────────────────────────────────────────────────
// Session Expiration Constants
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Maximum session age in milliseconds (24 hours).
 * Sessions older than this will be cleared during hydration.
 */
const SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * LocalStorage key for tracking session start time.
 */
const SESSION_TIMESTAMP_KEY = 'nomadic-session-timestamp';

// ─────────────────────────────────────────────────────────────────────────────
// Session Expiration Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Get the session start timestamp from localStorage.
 * @returns The timestamp in milliseconds, or null if not set.
 */
function getSessionTimestamp(): number | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(SESSION_TIMESTAMP_KEY);
  if (!stored) return null;
  const parsed = parseInt(stored, 10);
  return isNaN(parsed) ? null : parsed;
}

/**
 * Set the session start timestamp in localStorage.
 * Should be called when a new session is created.
 */
export function setSessionTimestamp(): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(SESSION_TIMESTAMP_KEY, Date.now().toString());
}

/**
 * Clear the session timestamp from localStorage.
 * Should be called when session is invalidated or user logs out.
 */
export function clearSessionTimestamp(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(SESSION_TIMESTAMP_KEY);
}

/**
 * Check if the current session has expired.
 * A session is considered expired if it's older than SESSION_MAX_AGE_MS.
 *
 * @returns true if expired or no timestamp exists, false otherwise.
 */
function isSessionExpired(): boolean {
  const timestamp = getSessionTimestamp();
  if (timestamp === null) {
    // No timestamp = treat as new session (not expired, but will need to be set)
    return false;
  }
  return Date.now() - timestamp > SESSION_MAX_AGE_MS;
}

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

  /**
   * Callback when session is expired and needs to be reset.
   * Called before clearing state to allow parent component to handle cleanup.
   */
  onSessionExpired?: () => void;
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
 * 1. Checks if session has expired (>24 hours old)
 * 2. If expired, clears state and returns (user starts fresh)
 * 3. Fetches document from documentStore (cached or API)
 * 4. If document exists with branches, restores all state
 * 5. Converts server-side ID selections to tile objects
 * 6. Selects the primary branch (or first branch as fallback)
 * 7. If primary branch lacks tiles, fetches them from API
 *
 * Session expiration (Tier 10 improvement):
 * - Sessions older than 24 hours are considered stale
 * - On expiration, state is cleared and user starts a new session
 * - This prevents data loss from stale/invalid sessions
 *
 * TODO: Consider adding retry logic for failed hydration.
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
    onSessionExpired,
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

        // Check for session expiration before fetching document
        // This prevents loading stale data that may cause issues
        if (isSessionExpired()) {
          console.info('Session expired (>24 hours old), starting fresh session');
          // Clear session timestamp and notify parent
          clearSessionTimestamp();
          onSessionExpired?.();
          // Clear local state to start fresh
          setBranches([]);
          setTilesMap({});
          setBranchSelections({});
          setSelectedBranchId(null);
          setTilesBranchId(null);
          // Set new session timestamp for fresh session
          setSessionTimestamp();
          onToast('Your previous session has expired. Starting a new trip planning session.');
          return;
        }

        // Fetch document from store (handles caching internally)
        const doc = await fetchDocument();
        if (cancelled) return;

        // No document or no branches - nothing to restore
        // Set session timestamp for new sessions
        if (!doc || !doc.branches.length) {
          if (getSessionTimestamp() === null) {
            setSessionTimestamp();
          }
          return;
        }

        // Restore core state from document
        setBranches(doc.branches);
        setTilesMap(doc.tiles);

        // Update session timestamp since we have a valid session to restore
        // (keeps the session alive as long as user is actively using it)
        if (getSessionTimestamp() === null) {
          setSessionTimestamp();
        }

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
            // Use fetchWithRetry for automatic retry on transient errors
            const res = await fetchWithRetry(
              `/api/document/tiles/${encodeURIComponent(fallbackBranchId)}`,
              {
                method: 'POST',
                signal: controller.signal,
              },
              {
                maxRetries: 3,
                baseDelay: 1000,
                onRetry: (attempt, error) => {
                  console.info(`Hydration tile fetch retry ${attempt}:`, error);
                },
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
