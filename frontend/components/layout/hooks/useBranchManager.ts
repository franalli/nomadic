'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { apiFetch, clearSessionLocalStorage, refreshTiles, resetSession } from '@/lib/api';
import { saveTripSummary } from '@/lib/summary';
import { useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import { clearPersistedUIState } from '@/state/uiStore';
import type { DocumentBranch, DocumentTripInputs, GraphPlanResponse, PlanStatus } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { TripSummaryPayload } from '@/types/summary';
import type { Tile, TileSelection } from '@/types/tile';

import { useBranchState } from './useBranchState';
import { clearSessionTimestamp, useSessionHydration } from './useSessionHydration';
import { EMPTY_TILE_SELECTION, selectionsToTileSelection, useTileSelection } from './useTileSelection';

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Minimum time to show the generating loader (in milliseconds).
 *
 * Set to 5s to match the GeneratingLoader animation duration (5 stages × 1s each).
 * This ensures the plan is fully generated with strategy content when branches appear.
 */
const GENERATING_MIN_DURATION_MS = 5000;

/**
 * Options for the useBranchManager hook.
 */
export interface BranchManagerOptions {
  /**
   * Current trip inputs from the form.
   * Used to determine if we have enough info to generate a plan.
   */
  tripInputs: DocumentTripInputs;

  /**
   * Ref to the chat panel container element.
   * Used to scroll and focus after starting a new session.
   */
  chatPanelContainerRef: React.RefObject<HTMLDivElement | null>;

  /**
   * Ref to the chat panel (currently unused after removing auto-trigger).
   * Kept for potential future use.
   */
  chatPanelRef?: React.RefObject<{ sendMessage: (text: string) => void } | null>;

  /**
   * Whether a plan has ever been generated in this session.
   * When true, regeneration should be silent (no chat messages).
   * Defaults to false if not provided.
   */
  hasEverHadPlan?: boolean;

  /**
   * Toast notification callback.
   * Used to show success/error messages to the user.
   */
  onToast: (message: string, type?: ToastType) => void;

  /**
   * Callback to increment the chat key.
   * Used to reset the chat panel when starting a new session.
   */
  onChatKeyIncrement: () => void;

  /**
   * Callback to reset the trip inputs draft.
   * Used when clearing context or starting a new session.
   */
  resetDraft: () => void;
}

/**
 * Payload received when a plan is generated.
 * Contains all branches, tiles, and metadata from the AI response.
 */
export interface PlanResultPayload {
  /** Trip context ID (null for anonymous sessions) */
  tripContextId: number | null;
  /** Generated trip branches (suggestions) */
  branches: DocumentBranch[];
  /** Map of all tiles referenced by branches */
  tiles: Record<string, Tile>;
  /** ID of the primary (recommended) branch */
  primaryBranchId: string | null;
  /** Updated trip inputs (if AI inferred any) */
  tripInputs?: DocumentTripInputs | null;
  /** Whether we have enough info to generate another plan */
  readyToGenerate?: boolean;
  /** Full API response for store updates */
  response?: GraphPlanResponse;
}

/**
 * State values from the branch manager.
 */
export interface BranchManagerState {
  branches: DocumentBranch[];
  selectedBranchId: string | null;
  tilesBranchId: string | null;
  branchSelections: Record<string, TileSelection>;
  isGenerating: boolean;
  isHydratingSnapshot: boolean;
  /** Plan regeneration status: ready, stale, or updating */
  planStatus: PlanStatus;
  /** Whether a regeneration is currently in-flight */
  isRegenerating: boolean;
}

/**
 * Computed values derived from state.
 */
export interface BranchManagerComputed {
  selectedBranch: DocumentBranch | null;
  activeBranchSelection: TileSelection;
  tiles: Tile[];
  readyToGenerate: boolean;
  hasBranchesReady: boolean;
}

/**
 * Actions available from the branch manager.
 */
export interface BranchManagerActions {
  setBranches: React.Dispatch<React.SetStateAction<DocumentBranch[]>>;
  setSelectedBranchId: React.Dispatch<React.SetStateAction<string | null>>;
  handleBranchSelect: (branchId: string) => Promise<void>;
  handleStartNewSession: () => Promise<void>;
  handlePlanResult: (result: PlanResultPayload) => void;
  handleTileSelection: (tile: Tile) => void;
  handleBookTrip: (branchId: string) => void;
  handleGeneratePlanStart: () => void;
}

/**
 * Complete return type combining state, computed values, and actions.
 */
export type UseBranchManagerReturn = BranchManagerState &
  BranchManagerComputed &
  BranchManagerActions;

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Main hook for managing the branch-based trip planning experience.
 *
 * This is the primary orchestration hook that composes several focused hooks:
 * - `useBranchState`: Core branch and tile state management
 * - `useTileSelection`: Tile selection/deselection logic
 * - `useSessionHydration`: Session restoration on mount
 *
 * It also manages:
 * - Generating state with minimum loading time
 * - Session reset flow
 * - Plan result handling
 * - Trip booking flow
 *
 * @param options - Configuration options
 * @returns Combined state, computed values, and actions
 *
 * @remarks
 * This hook was decomposed from a 650+ line monolith to improve:
 * - **Testability**: Each sub-hook can be tested in isolation
 * - **Readability**: Clear separation of concerns
 * - **Reusability**: Sub-hooks can be used independently if needed
 * - **Maintainability**: Changes are localized to relevant hooks
 *
 * The decomposition follows the principle of single responsibility:
 * - Branch state → useBranchState
 * - Tile selection → useTileSelection
 * - Session hydration → useSessionHydration
 * - Generating timer → local to this hook
 * - Session actions → local to this hook
 *
 * @example
 * ```tsx
 * const {
 *   branches,
 *   selectedBranch,
 *   tiles,
 *   isGenerating,
 *   handleTileSelection,
 *   handleBranchSelect,
 *   handleGeneratePlanStart,
 * } = useBranchManager({
 *   tripInputs,
 *   chatPanelContainerRef,
 *   onToast,
 *   onChatKeyIncrement,
 *   resetDraft,
 * });
 * ```
 */
export function useBranchManager(options: BranchManagerOptions): UseBranchManagerReturn {
  const {
    // tripInputs - no longer used, settings change detection uses document store directly
    chatPanelContainerRef,
    // hasEverHadPlan - no longer used, regeneration is now manual via RefreshButton
    onToast,
    onChatKeyIncrement,
    resetDraft,
  } = options;

  // PERF: Select only the sub-fields actually read (trip_inputs.origin for flight fetch,
  // trip_inputs settings for change detection). Avoids re-render on every document mutation.
  const tripInputsOrigin = useDocumentStore((s) => s.document?.trip_inputs?.origin);
  const tripInputsHotelSettings = useDocumentStore((s) => s.document?.trip_inputs?.hotel_settings);
  const tripInputsFlightSettings = useDocumentStore((s) => s.document?.trip_inputs?.flight_settings);
  const tripInputsActivitySettings = useDocumentStore((s) => s.document?.trip_inputs?.activity_settings);
  const fetchDocument = useDocumentStore((s) => s.fetchDocument);
  const selectTile = useDocumentStore((s) => s.selectTile);
  const deselectTile = useDocumentStore((s) => s.deselectTile);
  const hasAllRequiredFields = useDocumentStore((s) => s.hasAllRequiredFields);
  const resetDocumentStore = useDocumentStore((s) => s.reset);
  const setFromPlanResponse = useDocumentStore((s) => s.setFromPlanResponse);
  const resetChat = useChatStore((state) => state.resetChat);

  // ─────────────────────────────────────────────────────────────────────────
  // Compose Sub-Hooks
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Core branch and tile state management.
   * Handles branches, tiles, selections, and tile fetching.
   */
  const branchState = useBranchState({ onToast });

  /**
   * Session hydration on mount.
   * Restores previous session from storage/API.
   */
  const { isHydratingSnapshot } = useSessionHydration({
    fetchDocument,
    setBranches: branchState.setBranches,
    setTilesMap: branchState.setTilesMap,
    setBranchSelections: branchState.setBranchSelections,
    setSelectedBranchId: branchState.setSelectedBranchId,
    setTilesBranchId: branchState.setTilesBranchId,
    onToast,
  });

  /**
   * Tile selection logic.
   * Handles selecting/deselecting tiles with category-specific rules.
   */
  const { activeBranchSelection, handleTileSelection } = useTileSelection({
    branchSelections: branchState.branchSelections,
    setBranchSelections: branchState.setBranchSelections,
    selectedBranchId: branchState.selectedBranchId,
    tilesBranchId: branchState.tilesBranchId,
    onSelectTile: selectTile,
    onDeselectTile: deselectTile,
    onToast,
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Local State
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Whether the AI is currently generating a plan.
   * True from when user submits until results are displayed.
   */
  const [isGenerating, setIsGenerating] = useState(false);

  /**
   * Regeneration state from document store.
   * Managed by usePreferenceAutoRegen hook wired up at NomadicLanding.tsx level.
   */
  const isRegenerating = useDocumentStore((s) => s.isRegenerating);

  /**
   * Plan status is always 'ready' since regeneration is now automatic via auto-expand.
   */
  const planStatus: PlanStatus = 'ready';

  // ─────────────────────────────────────────────────────────────────────────
  // Refs
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Timestamp when generating started.
   * Used to calculate remaining time for minimum loading duration.
   */
  const generatingStartTimeRef = useRef<number | null>(null);

  /**
   * Timer for delayed result display.
   * Used to enforce minimum loading duration.
   */
  const generatingTimerRef = useRef<NodeJS.Timeout | null>(null);

  /**
   * Previous settings values for change detection.
   * Used to determine when to trigger tile refresh.
   */
  const prevSettingsRef = useRef<{
    hotel_settings?: DocumentTripInputs['hotel_settings'];
    flight_settings?: DocumentTripInputs['flight_settings'];
    activity_settings?: DocumentTripInputs['activity_settings'];
  } | null>(null);

  /**
   * Flag to track if tiles refresh is in progress.
   * Prevents concurrent refresh requests.
   */
  const isRefreshingRef = useRef(false);

  // ─────────────────────────────────────────────────────────────────────────
  // Computed Values
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Whether we have enough info to generate a new plan.
   * Requires all required fields AND no existing branches.
   */
  const readyToGenerate = hasAllRequiredFields() && branchState.branches.length === 0;

  // ─────────────────────────────────────────────────────────────────────────
  // Actions
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Clears all local state and resets to initial state.
   * Used internally when starting a new session or clearing context.
   */
  const handleClearContext = useCallback(() => {
    branchState.abortTilesFetch();

    // Clear any pending generating state
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
    setIsGenerating(false);
    generatingStartTimeRef.current = null;

    // Reset branch state
    branchState.setBranches([]);
    branchState.setSelectedBranchId(null);
    branchState.setTilesMap({});
    branchState.setTilesBranchId(null);
    branchState.setBranchSelections({});

    // Reset the draft to defaults
    resetDraft();

    // Reset the document store
    resetDocumentStore();

    // Increment chat key to reset the chat panel
    onChatKeyIncrement();
  }, [branchState, resetDocumentStore, resetDraft, onChatKeyIncrement]);

  /**
   * Starts a completely new planning session.
   *
   * This:
   * 1. Aborts any in-flight requests
   * 2. Resets the server-side session
   * 3. Clears all local state
   * 4. Scrolls to and focuses the chat input
   *
   * Shows a toast indicating whether server reset succeeded.
   */
  const handleStartNewSession = useCallback(async () => {
    console.log('[branchManager.startNewSession] 🔄 Starting server reset...');
    branchState.abortTilesFetch();
    let didResetServerState = false;

    try {
      const res = await resetSession();
      didResetServerState = res.ok;
      console.log('[branchManager.startNewSession] Server DELETE /api/session →', res.status, res.ok ? '✅' : '❌');

      // Re-establish session cookies after DELETE clears them.
      // Without this, the CSRF cookie is gone and all subsequent
      // POST/DELETE requests fail with 403 Forbidden.
      await apiFetch('/api/document');
      console.log('[branchManager.startNewSession] ✅ Session re-established (fresh CSRF cookie)');
    } catch (error) {
      console.error('[branchManager.startNewSession] ❌ Server reset failed:', error);
    } finally {
      // Clear session-related localStorage (preserves consent preferences)
      clearSessionLocalStorage();

      // Clear session timestamp so next page load doesn't try to hydrate stale session
      clearSessionTimestamp();

      // Clear persisted UI state (selectedBranchId, comparison mode) from localStorage
      clearPersistedUIState();

      handleClearContext();

      // Reset chat store to clear messages and session state
      resetChat();

      // Scroll to chat panel and focus input after reset
      setTimeout(() => {
        if (chatPanelContainerRef.current) {
          chatPanelContainerRef.current.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
          });
          // Focus the textarea input if it exists
          const input = chatPanelContainerRef.current.querySelector(
            'textarea'
          ) as HTMLTextAreaElement;
          if (input) {
            input.focus();
          }
        }
      }, 100);
    }

    onToast(
      didResetServerState
        ? 'Started a fresh planning session.'
        : 'Cleared your local planner, but the previous session may reappear if you refresh.',
      'success'
    );
  }, [branchState, handleClearContext, chatPanelContainerRef, onToast, resetChat]);

  /**
   * Finalizes the generating state and displays results.
   *
   * Called after minimum loading time has elapsed.
   * Updates all state from the plan result.
   */
  const finalizeGenerating = useCallback(
    (result: PlanResultPayload | null) => {
      if (!result) return;

      // Update document store from response
      if (result.response) {
        setFromPlanResponse(result.response);
      }

      // Update branch state
      branchState.setBranches(result.branches);
      branchState.setTilesMap(result.tiles);
      branchState.setTilesBranchId(result.primaryBranchId);

      // Convert ID-based selections to tile objects
      branchState.setBranchSelections(() => {
        const next: Record<string, TileSelection> = {};
        result.branches.forEach((branch) => {
          next[branch.id] = selectionsToTileSelection(branch.selections, result.tiles);
        });
        return next;
      });

      branchState.setSelectedBranchId(result.primaryBranchId);

      // Clear generating state
      setIsGenerating(false);
      generatingStartTimeRef.current = null;
    },
    [branchState, setFromPlanResponse]
  );

  /**
   * Handles plan generation result from the AI.
   *
   * Implements minimum loading time logic:
   * - If minimum time hasn't elapsed, schedules delayed display
   * - If minimum time has elapsed, displays immediately
   * - If error (no branches), clears generating state
   *
   * @param result - The plan result from the AI
   */
  const handlePlanResult = useCallback(
    (result: PlanResultPayload) => {
      const hasBranchesInResult = result.branches.length > 0;
      const isCurrentlyGenerating = generatingStartTimeRef.current !== null;

      // If generating and got branches, apply minimum loading time
      if (isCurrentlyGenerating && hasBranchesInResult) {
        const elapsed = Date.now() - generatingStartTimeRef.current!;
        const remaining = GENERATING_MIN_DURATION_MS - elapsed;

        if (remaining > 0) {
          // Schedule delayed display
          generatingTimerRef.current = setTimeout(() => {
            finalizeGenerating(result);
          }, remaining);
          return;
        }
      }

      // If generating but got error (no branches), clear generating state
      if (isCurrentlyGenerating && !hasBranchesInResult) {
        setIsGenerating(false);
        generatingStartTimeRef.current = null;
        if (generatingTimerRef.current) {
          clearTimeout(generatingTimerRef.current);
          generatingTimerRef.current = null;
        }
      }

      // Apply result immediately
      finalizeGenerating(result);
    },
    [finalizeGenerating]
  );

  /**
   * Books the selected trip configuration.
   *
   * Saves the trip summary to local storage and redirects to the summary page.
   * The summary page displays the selected options for booking.
   *
   * @param branchId - The branch to book
   */
  const handleBookTrip = useCallback(
    (branchId: string) => {
      console.log('[handleBookTrip] Called with branchId:', branchId);
      console.log('[handleBookTrip] Available branches:', branchState.branches.map(b => ({ id: b.id, dest: b.destination })));

      const branch = branchState.branches.find((b) => b.id === branchId);
      if (!branch) {
        console.error('[handleBookTrip] Branch not found! branchId:', branchId, 'available IDs:', branchState.branches.map(b => b.id));
        return;
      }

      const selection = branchState.branchSelections[branchId] ?? EMPTY_TILE_SELECTION;

      // Build summary payload
      const payload: TripSummaryPayload = {
        branch,
        selection: {
          stay: selection.stay,
          flight: selection.flight,
          activities: selection.activities ?? [],
        },
        tiles: branchState.tilesBranchId === branchId ? branchState.tiles : [],
        note: null,
        generatedAt: new Date().toISOString(),
      };

      console.log('[handleBookTrip] Saving payload:', payload);

      // Save to local storage and redirect
      saveTripSummary(payload);

      // Verify the save worked
      const saved = localStorage.getItem('nomadic_trip_summary');
      console.log('[handleBookTrip] Verified localStorage:', saved ? 'saved successfully' : 'SAVE FAILED');

      window.location.href = '/summary';
    },
    [branchState.branches, branchState.branchSelections, branchState.tiles, branchState.tilesBranchId]
  );

  /**
   * Marks the start of plan generation.
   *
   * Called when user submits a message that triggers plan generation.
   * Starts the minimum loading timer.
   */
  const handleGeneratePlanStart = useCallback(() => {
    setIsGenerating(true);
    generatingStartTimeRef.current = Date.now();

    // Clear any existing timer
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Effects
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Cleanup tiles fetch on unmount.
   * Prevents memory leaks and state updates after unmount.
   */
  useEffect(
    () => () => {
      branchState.abortTilesFetch();
    },
    [branchState]
  );

  /**
   * Cleanup generating timer on unmount.
   * Prevents delayed state updates after unmount.
   */
  useEffect(() => {
    return () => {
      if (generatingTimerRef.current) {
        clearTimeout(generatingTimerRef.current);
      }
    };
  }, []);

  /**
   * Detect settings changes and refresh tiles accordingly.
   *
   * When hotel_settings, flight_settings, or activity_settings change,
   * this effect triggers a tile refresh for the affected verticals.
   * This ensures tiles always reflect the current user preferences.
   */
  useEffect(() => {
    const selectedBranchId = branchState.selectedBranchId;

    // Skip if no settings, no branch selected, or currently generating
    if ((!tripInputsHotelSettings && !tripInputsFlightSettings && !tripInputsActivitySettings) || !selectedBranchId || isGenerating) {
      return;
    }

    const currentSettings = {
      hotel_settings: tripInputsHotelSettings,
      flight_settings: tripInputsFlightSettings,
      activity_settings: tripInputsActivitySettings,
    };

    const prevSettings = prevSettingsRef.current;

    // Initialize on first run
    if (!prevSettings) {
      prevSettingsRef.current = currentSettings;
      return;
    }

    // Detect which verticals have changed settings
    const changedVerticals: ('hotel' | 'flight' | 'activity')[] = [];

    // Compare hotel settings
    const prevHotel = prevSettings.hotel_settings;
    const currHotel = currentSettings.hotel_settings;
    if (
      prevHotel?.min_stars !== currHotel?.min_stars ||
      JSON.stringify(prevHotel?.amenities) !== JSON.stringify(currHotel?.amenities)
    ) {
      changedVerticals.push('hotel');
    }

    // Compare flight settings
    const prevFlight = prevSettings.flight_settings;
    const currFlight = currentSettings.flight_settings;
    if (
      prevFlight?.cabin_class !== currFlight?.cabin_class ||
      prevFlight?.direct_only !== currFlight?.direct_only ||
      prevFlight?.round_trip !== currFlight?.round_trip
    ) {
      changedVerticals.push('flight');
    }

    // Compare activity settings
    const prevActivity = prevSettings.activity_settings;
    const currActivity = currentSettings.activity_settings;
    if (
      JSON.stringify(prevActivity?.categories) !== JSON.stringify(currActivity?.categories) ||
      prevActivity?.skill_level !== currActivity?.skill_level
    ) {
      changedVerticals.push('activity');
    }

    // Update ref before triggering refresh
    prevSettingsRef.current = currentSettings;

    // If no changes or already refreshing, skip
    if (changedVerticals.length === 0 || isRefreshingRef.current) {
      return;
    }

    // Trigger tile refresh for changed verticals
    isRefreshingRef.current = true;

    refreshTiles(selectedBranchId, changedVerticals)
      .then((response) => {
        // Update tiles map with refreshed tiles
        const newTilesMap: Record<string, Tile> = {};
        for (const tile of response.tiles) {
          newTilesMap[tile.id] = tile;
        }
        branchState.setTilesMap((prev) => ({ ...prev, ...newTilesMap }));
      })
      .catch((error) => {
        console.error('Failed to refresh tiles after settings change:', error);
      })
      .finally(() => {
        isRefreshingRef.current = false;
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- branchState object recreated each render; individual properties listed instead
  }, [
    tripInputsHotelSettings,
    tripInputsFlightSettings,
    tripInputsActivitySettings,
    branchState.selectedBranchId,
    branchState.setTilesMap,
    isGenerating,
  ]);

  // ─────────────────────────────────────────────────────────────────────────
  // Auto-fetch missing flights
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Ref to track if we've already attempted to fetch missing flights for this branch.
   * Prevents infinite fetch loops.
   */
  const fetchedMissingFlightsRef = useRef<Set<string>>(new Set());

  /**
   * Auto-fetch missing flights when tiles are loaded but flights are empty.
   * This handles the case where curated content (hotels/activities) is loaded
   * but live flights need to be fetched from Amadeus.
   */
  useEffect(() => {
    const selectedBranchId = branchState.selectedBranchId;
    const tilesBranchId = branchState.tilesBranchId;
    const selectedBranch = branchState.selectedBranch;

    // Skip if no branch selected or tiles not loaded for this branch
    if (!selectedBranchId || !selectedBranch) {
      return;
    }

    // Skip if tiles aren't loaded yet for this branch
    if (tilesBranchId !== selectedBranchId) {
      return;
    }

    // Skip if currently generating or refreshing
    if (isGenerating || isRefreshingRef.current) {
      return;
    }

    // Skip if we already attempted to fetch flights for this branch
    if (fetchedMissingFlightsRef.current.has(selectedBranchId)) {
      return;
    }

    // Check if flights are missing (with null safety)
    const flightIds = selectedBranch.tiles?.flights ?? [];
    const hasFlights = flightIds.length > 0;
    if (hasFlights) {
      return;
    }

    // Check if we have origin (required for flight search)
    const origin = selectedBranch.origin || tripInputsOrigin;
    if (!origin) {
      console.log('[useBranchManager] No origin available for flight fetch');
      return;
    }

    // Mark this branch as attempted
    fetchedMissingFlightsRef.current.add(selectedBranchId);

    // Fetch missing flights
    console.log('[useBranchManager] Auto-fetching missing flights for branch:', selectedBranchId);
    isRefreshingRef.current = true;

    refreshTiles(selectedBranchId, ['flight'])
      .then((response) => {
        if (response.tiles.length > 0) {
          // Update tiles map with fetched flights
          const newTilesMap: Record<string, Tile> = {};
          for (const tile of response.tiles) {
            newTilesMap[tile.id] = tile;
          }
          branchState.setTilesMap((prev) => ({ ...prev, ...newTilesMap }));

          // Update branch tile IDs
          branchState.setBranches((prevBranches) =>
            prevBranches.map((b) => {
              if (b.id !== selectedBranchId) return b;
              return {
                ...b,
                tiles: {
                  ...b.tiles,
                  flights: response.tiles.filter((t) => t.type === 'flight').map((t) => t.id),
                },
              };
            })
          );

          console.log('[useBranchManager] Fetched', response.tiles.length, 'flight tiles');
        }
      })
      .catch((error) => {
        console.error('[useBranchManager] Failed to fetch missing flights:', error);
      })
      .finally(() => {
        isRefreshingRef.current = false;
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps -- branchState object recreated each render; individual properties listed instead
  }, [
    branchState.selectedBranchId,
    branchState.tilesBranchId,
    branchState.selectedBranch,
    branchState.setTilesMap,
    branchState.setBranches,
    tripInputsOrigin,
    isGenerating,
  ]);

  // ─────────────────────────────────────────────────────────────────────────
  // Return
  // ─────────────────────────────────────────────────────────────────────────

  return {
    // State (from branchState)
    branches: branchState.branches,
    selectedBranchId: branchState.selectedBranchId,
    tilesBranchId: branchState.tilesBranchId,
    branchSelections: branchState.branchSelections,

    // State (local)
    isGenerating,
    isHydratingSnapshot,
    planStatus,
    isRegenerating,

    // Computed (from branchState)
    selectedBranch: branchState.selectedBranch,
    tiles: branchState.tiles,
    hasBranchesReady: branchState.hasBranchesReady,

    // Computed (from useTileSelection)
    activeBranchSelection,

    // Computed (local)
    readyToGenerate,

    // Actions (from branchState)
    setBranches: branchState.setBranches,
    setSelectedBranchId: branchState.setSelectedBranchId,
    handleBranchSelect: branchState.handleBranchSelect,

    // Actions (from useTileSelection)
    handleTileSelection,

    // Actions (local)
    handleStartNewSession,
    handlePlanResult,
    handleBookTrip,
    handleGeneratePlanStart,
  };
}
