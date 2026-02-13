'use client';

import { useCallback, useMemo } from 'react';

import { isActivityType, isFlightType } from '@/lib/utils';
import type { Tile, TileSelection } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Shared empty selection object to avoid re-creating on each render.
 * Used as a default value when no selection exists for a branch.
 */
export const EMPTY_TILE_SELECTION: TileSelection = { activities: [] };

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Category of a tile for selection purposes.
 * Maps to the three main tile types in the UI:
 * - 'stay': Hotels, accommodations
 * - 'flight': Flights, transportation
 * - 'activity': Tours, experiences, attractions
 */
export type SelectionCategory = 'stay' | 'flight' | 'activity';

/**
 * Options for the useTileSelection hook.
 */
export interface UseTileSelectionOptions {
  /**
   * Current tile selections indexed by branch ID.
   * Each branch maintains its own independent selection state.
   */
  branchSelections: Record<string, TileSelection>;

  /**
   * Setter function to update branch selections.
   * Called when user selects/deselects a tile.
   */
  setBranchSelections: React.Dispatch<React.SetStateAction<Record<string, TileSelection>>>;

  /**
   * Currently selected branch ID.
   * Used to determine which branch's selections to modify.
   */
  selectedBranchId: string | null;

  /**
   * Branch ID for which tiles are currently loaded.
   * May differ from selectedBranchId during branch switching.
   * Takes precedence over selectedBranchId when determining target branch.
   */
  tilesBranchId: string | null;

  /**
   * Callback to sync tile selection to the backend.
   * Called after local state is updated.
   *
   * @param branchId - The branch to update
   * @param tileId - The tile being selected
   * @param tileType - The type of tile ('stay', 'flight', or 'activity')
   */
  onSelectTile: (branchId: string, tileId: string, tileType: 'stay' | 'flight' | 'activity') => Promise<void>;

  /**
   * Callback to sync tile deselection to the backend.
   * Called after local state is updated.
   *
   * @param branchId - The branch to update
   * @param tileType - The type of tile being deselected
   * @param tileId - The tile being deselected
   */
  onDeselectTile: (branchId: string, tileType: 'stay' | 'flight' | 'activity', tileId: string) => Promise<void>;

  /**
   * Toast notification callback for error messages.
   */
  onToast: (message: string) => void;
}

/**
 * Return type for the useTileSelection hook.
 */
export interface UseTileSelectionReturn {
  /**
   * The current tile selection for the active branch.
   * Returns EMPTY_TILE_SELECTION if no branch is selected.
   */
  activeBranchSelection: TileSelection;

  /**
   * Handler to toggle tile selection.
   * Automatically determines the tile category and handles:
   * - Single-select for stays and flights (replaces previous selection)
   * - Multi-select for activities (with overlap detection)
   *
   * @param tile - The tile to select or deselect
   */
  handleTileSelection: (tile: Tile) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helper Functions
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Determines the selection category for a tile based on its type.
 *
 * @param tile - The tile to categorize
 * @returns The selection category ('stay', 'flight', or 'activity')
 */
const resolveSelectionCategory = (tile: Tile): SelectionCategory => {
  const type = tile.type || '';
  if (isFlightType(type)) return 'flight';
  if (isActivityType(type)) return 'activity';
  return 'stay';
};

/**
 * Parses a date value from tile metadata.
 *
 * @param value - The raw value from tile metadata (string, null, or undefined)
 * @returns A Date object if valid, null otherwise
 *
 * @remarks
 * Handles various date formats that may come from the API.
 * Returns null for invalid dates to allow graceful fallback.
 */
const parseDateValue = (value: unknown): Date | null => {
  if (!value || typeof value !== 'string') return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

/**
 * Extracts the date range for an activity tile from its metadata.
 *
 * @param tile - The activity tile to extract dates from
 * @returns An object with start and end dates (may be null if not available)
 *
 * @remarks
 * Supports multiple metadata field names for flexibility with different API responses:
 * - Start: start_date, date, date_time, start, activity_date
 * - End: end_date, end, activity_end
 *
 * If only start date is available, end defaults to start (point-in-time activity).
 *
 * TODO: Once API response format is standardized, simplify to use consistent field names.
 * Current flexibility is needed to support various tile sources during development.
 */
const extractActivityRange = (tile: Tile): { start?: Date | null; end?: Date | null } => {
  const meta = (tile.meta as Record<string, unknown> | undefined) ?? {};
  const startRaw =
    meta.start_date ?? meta.date ?? meta.date_time ?? meta.start ?? meta.activity_date;
  const endRaw = meta.end_date ?? meta.end ?? meta.activity_end;
  const start = parseDateValue(startRaw);
  const end = parseDateValue(endRaw) ?? start;
  return { start, end };
};

/**
 * Checks if two activity tiles have overlapping time ranges.
 *
 * @param a - First activity tile
 * @param b - Second activity tile
 * @returns true if the activities overlap in time, false otherwise
 *
 * @remarks
 * Used to automatically deselect conflicting activities when a new one is selected.
 * This prevents users from booking activities that would happen at the same time.
 *
 * Returns false if either activity lacks valid date information, allowing selection
 * even when overlap cannot be determined. This is a permissive approach to avoid
 * blocking users when metadata is incomplete.
 *
 * TODO: Consider making this more strict once all activity tiles have reliable date metadata.
 * Could also add a warning toast when selecting activities with missing date info.
 */
const activitiesOverlap = (a: Tile, b: Tile): boolean => {
  const rangeA = extractActivityRange(a);
  const rangeB = extractActivityRange(b);
  const startA = rangeA.start;
  const startB = rangeB.start;
  const endA = rangeA.end ?? startA;
  const endB = rangeB.end ?? startB;
  if (!startA || !startB || !endA || !endB) return false;
  return startA.getTime() <= endB.getTime() && startB.getTime() <= endA.getTime();
};

/**
 * Converts server-side ID-based selections to UI-friendly object-based selections.
 *
 * @param selections - ID-based selections from the server (stay ID, flight ID, activity IDs)
 * @param tilesMap - Map of tile IDs to tile objects
 * @returns A TileSelection object with resolved tile references
 *
 * @remarks
 * The server stores selections as tile IDs for efficiency.
 * The UI needs full tile objects for rendering.
 * This function bridges the gap by looking up tiles from the map.
 *
 * Missing tiles are skipped with a console warning. This can happen if:
 * - Tiles were removed from the branch after selection
 * - There's a data inconsistency between branches and tiles
 * - Session was restored with stale tile data
 *
 * TODO: Consider adding error recovery - could trigger a tile refresh if many lookups fail.
 */
export const selectionsToTileSelection = (
  selections: { stay?: string | null; flight?: string | null; activities: string[] } | undefined,
  tilesMap: Record<string, Tile>
): TileSelection => {
  if (!selections) return EMPTY_TILE_SELECTION;
  const result: TileSelection = { activities: [] };

    if (selections.stay) {
      const stayTile = tilesMap[selections.stay];
      if (stayTile) {
        result.stay = stayTile;
      } else if (process.env.NODE_ENV !== 'production') {
        console.warn(`selectionsToTileSelection: stay tile "${selections.stay}" not found in tilesMap`);
      }
    }    if (selections.flight) {
      const flightTile = tilesMap[selections.flight];
      if (flightTile) {
        result.flight = flightTile;
      } else if (process.env.NODE_ENV !== 'production') {
        console.warn(`selectionsToTileSelection: flight tile "${selections.flight}" not found in tilesMap`);
      }
    }    for (const activityId of selections.activities) {
      const activityTile = tilesMap[activityId];
      if (activityTile) {
        result.activities.push(activityTile);
      } else if (process.env.NODE_ENV !== 'production') {
        console.warn(`selectionsToTileSelection: activity tile "${activityId}" not found in tilesMap`);
      }
    }  return result;
};

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Hook for managing tile selections within branches.
 *
 * Handles the logic for:
 * - Computing the active branch's current selection
 * - Toggling tile selection/deselection
 * - Enforcing single-select for stays and flights
 * - Managing multi-select for activities with overlap detection
 * - Syncing selections to the backend
 *
 * @param options - Configuration options for the hook
 * @returns Selection state and handlers
 *
 * @example
 * ```tsx
 * const { activeBranchSelection, handleTileSelection } = useTileSelection({
 *   branchSelections,
 *   setBranchSelections,
 *   selectedBranchId,
 *   tilesBranchId,
 *   onSelectTile: documentStore.selectTile,
 *   onDeselectTile: documentStore.deselectTile,
 *   onToast,
 * });
 *
 * // In tile click handler:
 * handleTileSelection(clickedTile);
 * ```
 */
export function useTileSelection(options: UseTileSelectionOptions): UseTileSelectionReturn {
  const {
    branchSelections,
    setBranchSelections,
    selectedBranchId,
    tilesBranchId,
    onSelectTile,
    onDeselectTile,
    onToast,
  } = options;

  /**
   * Memoized selection for the currently active branch.
   * Returns empty selection if no branch is selected.
   */
  const activeBranchSelection = useMemo(
    () =>
      selectedBranchId
        ? (branchSelections[selectedBranchId] ?? EMPTY_TILE_SELECTION)
        : EMPTY_TILE_SELECTION,
    [branchSelections, selectedBranchId]
  );

  /**
   * Handles tile selection/deselection with category-specific logic:
   *
   * - **Stays**: Single-select. Clicking a new stay replaces the previous one.
   *   Clicking the selected stay deselects it.
   *
   * - **Flights**: Single-select. Same behavior as stays.
   *
   * - **Activities**: Multi-select with overlap detection. Clicking a new activity
   *   adds it to the list, automatically removing any activities with overlapping
   *   time ranges. Clicking a selected activity removes it.
   *
   * Updates local state synchronously for immediate UI feedback, then syncs
   * to the backend asynchronously. Backend sync failures show a toast but
   * don't revert local state (optimistic update pattern).
   */
  const handleTileSelection = useCallback(
    (tile: Tile) => {
      // Determine which branch to modify
      // tilesBranchId takes precedence as it represents the currently loaded tiles
      const branchId = tilesBranchId ?? selectedBranchId;
      if (!branchId) return;

      // Get current selection for this branch
      const current = branchSelections[branchId] ?? EMPTY_TILE_SELECTION;

      // Build the next selection state
      const nextSelection: TileSelection = {
        stay: current.stay,
        flight: current.flight,
        activities: [...current.activities],
      };

      const category = resolveSelectionCategory(tile);
      let isDeselect = false;

      if (category === 'stay') {
        // Single-select: toggle or replace
        isDeselect = Boolean(current.stay && current.stay.id === tile.id);
        nextSelection.stay = isDeselect ? undefined : tile;
      } else if (category === 'flight') {
        // Single-select: toggle or replace
        isDeselect = Boolean(current.flight && current.flight.id === tile.id);
        nextSelection.flight = isDeselect ? undefined : tile;
      } else {
        // Multi-select with overlap detection
        const existingIdx = nextSelection.activities.findIndex(
          (activity) => activity.id === tile.id
        );
        if (existingIdx >= 0) {
          // Deselect: remove from list
          isDeselect = true;
          nextSelection.activities.splice(existingIdx, 1);
        } else {
          // Select: add to list, removing overlapping activities
          const pruned = nextSelection.activities.filter(
            (activity) => !activitiesOverlap(activity, tile)
          );
          nextSelection.activities = [...pruned, tile];
        }
      }

      // Update local state synchronously for immediate UI feedback
      setBranchSelections((prev) => ({ ...prev, [branchId]: nextSelection }));

      // Sync to backend asynchronously (fire-and-forget with error handling)
      const tileType = category === 'stay' ? 'stay' : category === 'flight' ? 'flight' : 'activity';
      if (isDeselect) {
        onDeselectTile(branchId, tileType, tile.id).catch((err) => {
          console.error('Failed to sync tile deselection:', err);
          onToast('Failed to save selection. Please try again.');
        });
      } else {
        onSelectTile(branchId, tile.id, tileType).catch((err) => {
          console.error('Failed to sync tile selection:', err);
          onToast('Failed to save selection. Please try again.');
        });
      }
    },
    [branchSelections, selectedBranchId, tilesBranchId, setBranchSelections, onSelectTile, onDeselectTile, onToast]
  );

  return {
    activeBranchSelection,
    handleTileSelection,
  };
}
