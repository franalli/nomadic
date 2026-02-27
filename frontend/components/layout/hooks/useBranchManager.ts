/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useStoreWithEqualityFn } from 'zustand/traditional';

import { apiFetch, clearSessionLocalStorage, refreshTiles, resetSession } from '@/lib/api';
import { debugLog } from '@/lib/debug';
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
const MAX_MISSING_FLIGHT_RETRIES = 2;

/**
 * Options for the useBranchManager hook.
 */
interface BranchManagerOptions {
  /**
   * Ref to the chat panel container element.
   * Used to scroll and focus after starting a new session.
   */
  chatPanelContainerRef: React.RefObject<HTMLDivElement | null>;

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
interface BranchManagerState {
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
interface BranchManagerComputed {
  selectedBranch: DocumentBranch | null;
  activeBranchSelection: TileSelection;
  tiles: Tile[];
  readyToGenerate: boolean;
  hasBranchesReady: boolean;
}

/**
 * Actions available from the branch manager.
 */
interface BranchManagerActions {
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
type UseBranchManagerReturn = BranchManagerState &
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
    chatPanelContainerRef,
    onToast,
    onChatKeyIncrement,
    resetDraft,
  } = options;

  // Actions (stable refs — never trigger rerenders, 1 subscription)
  const { fetchDocument, selectTile, deselectTile, hasAllRequiredFields,
          resetDocumentStore, setFromPlanResponse } =
    useDocumentStore(useShallow((s) => ({
      fetchDocument: s.fetchDocument,
      selectTile: s.selectTile,
      deselectTile: s.deselectTile,
      hasAllRequiredFields: s.hasAllRequiredFields,
      resetDocumentStore: s.reset,
      setFromPlanResponse: s.setFromPlanResponse,
    })));

  // Reactive data (settings + origin + regenerating, 1 subscription)
  // JSON equality for settings objects — small objects, negligible cost
  const { tripInputsOrigin, tripInputsHotelSettings, tripInputsFlightSettings,
          tripInputsActivitySettings, isRegenerating } =
    useStoreWithEqualityFn(
      useDocumentStore,
      (s) => ({
        tripInputsOrigin: s.document?.trip_inputs?.origin,
        tripInputsHotelSettings: s.document?.trip_inputs?.hotel_settings,
        tripInputsFlightSettings: s.document?.trip_inputs?.flight_settings,
        tripInputsActivitySettings: s.document?.trip_inputs?.activity_settings,
        isRegenerating: s.isRegenerating,
      }),
      (a, b) =>
        a.tripInputsOrigin === b.tripInputsOrigin &&
        a.isRegenerating === b.isRegenerating &&
        JSON.stringify(a.tripInputsHotelSettings) === JSON.stringify(b.tripInputsHotelSettings) &&
        JSON.stringify(a.tripInputsFlightSettings) === JSON.stringify(b.tripInputsFlightSettings) &&
        JSON.stringify(a.tripInputsActivitySettings) === JSON.stringify(b.tripInputsActivitySettings)
    );

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
   * Tracks settings-triggered refresh progress.
   */
  const isSettingsRefreshingRef = useRef(false);

  /**
   * Tracks auto-flight refresh progress.
   */
  const isFlightsRefreshingRef = useRef(false);

  /**
   * Monotonic sequence used to discard stale settings refresh responses.
   */
  const refreshSeqRef = useRef(0);

  /**
   * Reactive tick bumped whenever a refresh settles.
   * Used to retrigger effects that depend on non-reactive refresh refs.
   */
  const [settingsRefreshTick, setSettingsRefreshTick] = useState(0);

  /**
   * Tracks branches where missing flights were already auto-fetched.
   */
  const fetchedMissingFlightsRef = useRef<Set<string>>(new Set());

  /**
   * Bounded retries for missing-flight auto-fetch per branch.
   */
  const missingFlightRetryCountRef = useRef<Record<string, number>>({});

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
    prevSettingsRef.current = null;
    isSettingsRefreshingRef.current = false;
    isFlightsRefreshingRef.current = false;
    refreshSeqRef.current = 0;
    fetchedMissingFlightsRef.current.clear();
    missingFlightRetryCountRef.current = {};

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
    debugLog('[branchManager.startNewSession] Starting server reset...');
    branchState.abortTilesFetch();
    let didResetServerState = false;

    // Step 1: Best-effort server-side session deletion
    try {
      const res = await resetSession();
      didResetServerState = res.ok;
      debugLog('[branchManager.startNewSession] Server DELETE /api/session ->', res.status);
    } catch (error) {
      debugLog('[branchManager.startNewSession] Server reset failed:', error);
    }

    // Step 2: Best-effort CSRF re-establishment.
    // If this 429s or fails, the CSRF cookie will be set on the next
    // successful API call naturally (e.g., when the remounted chat hydrates).
    try {
      const csrfRes = await apiFetch('/api/document');
      if (csrfRes.ok || csrfRes.status === 204) {
        debugLog('[branchManager.startNewSession] Session re-established (fresh CSRF cookie)');
      } else {
        debugLog('[branchManager.startNewSession] CSRF re-establishment returned', csrfRes.status);
      }
    } catch (csrfError) {
      debugLog('[branchManager.startNewSession] CSRF re-establishment failed, deferring:', csrfError);
    }

    // Step 3: Always clear local state (never fails)
    clearSessionLocalStorage();
    clearSessionTimestamp();
    clearPersistedUIState();
    handleClearContext();
    resetChat();

    // Step 4: Scroll to chat panel and focus input
    setTimeout(() => {
      if (chatPanelContainerRef.current) {
        chatPanelContainerRef.current.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
        const input = chatPanelContainerRef.current.querySelector(
          'textarea'
        ) as HTMLTextAreaElement;
        if (input) {
          input.focus();
        }
      }
    }, 100);

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

      if (generatingTimerRef.current) {
        clearTimeout(generatingTimerRef.current);
        generatingTimerRef.current = null;
      }

      // If generating and got branches, apply minimum loading time
      if (isCurrentlyGenerating && hasBranchesInResult) {
        const elapsed = Date.now() - generatingStartTimeRef.current!;
        const remaining = GENERATING_MIN_DURATION_MS - elapsed;

        if (remaining > 0) {
          // Schedule delayed display
          generatingTimerRef.current = setTimeout(() => {
            generatingTimerRef.current = null;
            finalizeGenerating(result);
          }, remaining);
          return;
        }
      }

      // If generating but got error (no branches), clear generating state
      if (isCurrentlyGenerating && !hasBranchesInResult) {
        setIsGenerating(false);
        generatingStartTimeRef.current = null;
        generatingTimerRef.current = null;
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
      debugLog('[handleBookTrip] Called with branchId:', branchId);
      debugLog('[handleBookTrip] Available branches:', branchState.branches.map(b => ({ id: b.id, dest: b.destination })));

      const branch = branchState.branches.find((b) => b.id === branchId);
      if (!branch) {
        debugLog('[handleBookTrip] Branch not found! branchId:', branchId, 'available IDs:', branchState.branches.map(b => b.id));
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

      debugLog('[handleBookTrip] Saving payload:', payload);

      // Save to local storage and redirect
      saveTripSummary(payload);

      // Verify the save worked
      const saved = localStorage.getItem('nomadic_trip_summary');
      debugLog('[handleBookTrip] Verified localStorage:', saved ? 'saved successfully' : 'SAVE FAILED');

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

  const abortTilesFetchOnUnmountRef = useRef(branchState.abortTilesFetch);
  useEffect(() => {
    abortTilesFetchOnUnmountRef.current = branchState.abortTilesFetch;
  }, [branchState.abortTilesFetch]);

  /**
   * Cleanup tiles fetch on unmount.
   * Prevents memory leaks and state updates after unmount.
   */
  useEffect(
    () => () => {
      abortTilesFetchOnUnmountRef.current();
    },
    []
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
    let cancelled = false;
    const selectedBranchId = branchState.selectedBranchId;

    // Skip if no settings, no branch selected, or currently generating
    if ((!tripInputsHotelSettings && !tripInputsFlightSettings && !tripInputsActivitySettings) || !selectedBranchId || isGenerating) {
      return () => { cancelled = true; };
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
      return () => { cancelled = true; };
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

    // If no changes, skip
    if (changedVerticals.length === 0) {
      return () => { cancelled = true; };
    }

    // Trigger tile refresh for changed verticals
    const refreshSeq = ++refreshSeqRef.current;
    const requestSettings = currentSettings;
    isSettingsRefreshingRef.current = true;

    refreshTiles(selectedBranchId, changedVerticals)
      .then((response) => {
        if (cancelled) return;
        if (refreshSeq !== refreshSeqRef.current) {
          debugLog('[settings refresh] Ignored stale refresh response', {
            selectedBranchId,
            changedVerticals,
            refreshSeq,
            latestSeq: refreshSeqRef.current,
          });
          return;
        }

        const latestTripInputs = useDocumentStore.getState().document?.trip_inputs;
        const latestSettings = {
          hotel_settings: latestTripInputs?.hotel_settings,
          flight_settings: latestTripInputs?.flight_settings,
          activity_settings: latestTripInputs?.activity_settings,
        };

        if (JSON.stringify(latestSettings) !== JSON.stringify(requestSettings)) {
          debugLog('[settings refresh] Ignored response after settings changed again', {
            selectedBranchId,
            changedVerticals,
          });
          return;
        }
        // Update tiles map with refreshed tiles
        const newTilesMap: Record<string, Tile> = {};
        for (const tile of response.tiles) {
          newTilesMap[tile.id] = tile;
        }
        branchState.setTilesMap((prev) => ({ ...prev, ...newTilesMap }));

        const refreshedStayIds = response.tiles
          .filter((tile) => tile.type === 'hotel' || tile.type === 'stay' || tile.type === 'accommodation')
          .map((tile) => tile.id);
        const refreshedFlightIds = response.tiles
          .filter((tile) => tile.type === 'flight')
          .map((tile) => tile.id);
        const refreshedActivityIds = response.tiles
          .filter((tile) =>
            tile.type === 'activity' ||
            tile.type === 'experience' ||
            tile.type === 'tour' ||
            tile.type === 'attraction'
          )
          .map((tile) => tile.id);

        branchState.setBranches((prevBranches) =>
          prevBranches.map((branch) => {
            if (branch.id !== selectedBranchId) return branch;
            const nextTiles = { ...(branch.tiles ?? {}) };
            if (changedVerticals.includes('hotel')) nextTiles.stays = refreshedStayIds;
            if (changedVerticals.includes('flight')) nextTiles.flights = refreshedFlightIds;
            if (changedVerticals.includes('activity')) nextTiles.activities = refreshedActivityIds;
            return { ...branch, tiles: nextTiles };
          })
        );
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Failed to refresh tiles after settings change:', error);
      })
      .finally(() => {
        if (refreshSeq === refreshSeqRef.current) {
          isSettingsRefreshingRef.current = false;
          if (!cancelled) {
            setSettingsRefreshTick((tick) => tick + 1);
          }
        }
      });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- branchState object recreated each render; individual properties listed instead
  }, [
    tripInputsHotelSettings,
    tripInputsFlightSettings,
    tripInputsActivitySettings,
    branchState.selectedBranchId,
    branchState.setTilesMap,
    branchState.setBranches,
    isGenerating,
    settingsRefreshTick,
  ]);

  // ─────────────────────────────────────────────────────────────────────────
  // Auto-fetch missing flights
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Auto-fetch missing flights when tiles are loaded but flights are empty.
   * This handles the case where curated content (hotels/activities) is loaded
   * but flights need to be fetched separately.
   */
  useEffect(() => {
    let cancelled = false;
    const selectedBranchId = branchState.selectedBranchId;
    const tilesBranchId = branchState.tilesBranchId;
    const selectedBranch = branchState.selectedBranch;

    // Skip if no branch selected or tiles not loaded for this branch
    if (!selectedBranchId || !selectedBranch) {
      return () => { cancelled = true; };
    }

    // Skip if tiles aren't loaded yet for this branch
    if (tilesBranchId !== selectedBranchId) {
      return () => { cancelled = true; };
    }

    // Skip if currently generating or refreshing
    if (isGenerating || isSettingsRefreshingRef.current || isFlightsRefreshingRef.current) {
      return () => { cancelled = true; };
    }

    // Skip if we already attempted to fetch flights for this branch
    if (fetchedMissingFlightsRef.current.has(selectedBranchId)) {
      return () => { cancelled = true; };
    }

    const retryCount = missingFlightRetryCountRef.current[selectedBranchId] ?? 0;
    if (retryCount >= MAX_MISSING_FLIGHT_RETRIES) {
      return () => { cancelled = true; };
    }

    // Check if flights are missing (with null safety)
    const flightIds = selectedBranch.tiles?.flights ?? [];
    const hasFlights = flightIds.length > 0;
    if (hasFlights) {
      return () => { cancelled = true; };
    }

    // Check if we have origin (required for flight search)
    const origin = selectedBranch.origin || tripInputsOrigin;
    if (!origin) {
      debugLog('[useBranchManager] No origin available for flight fetch');
      return () => { cancelled = true; };
    }

    // Fetch missing flights
    debugLog('[useBranchManager] Auto-fetching missing flights for branch:', selectedBranchId);
    isFlightsRefreshingRef.current = true;
    let shouldRetry = false;

    refreshTiles(selectedBranchId, ['flight'])
      .then((response) => {
        if (cancelled) return;
        const fetchedFlights = response.tiles.filter((t) => t.type === 'flight');
        if (fetchedFlights.length > 0) {
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
                  flights: fetchedFlights.map((t) => t.id),
                },
              };
            })
          );

          fetchedMissingFlightsRef.current.add(selectedBranchId);
          delete missingFlightRetryCountRef.current[selectedBranchId];
          debugLog('[useBranchManager] Fetched', response.tiles.length, 'flight tiles');
        } else {
          fetchedMissingFlightsRef.current.delete(selectedBranchId);
          const nextRetry = (missingFlightRetryCountRef.current[selectedBranchId] ?? 0) + 1;
          missingFlightRetryCountRef.current[selectedBranchId] = nextRetry;
          shouldRetry = nextRetry < MAX_MISSING_FLIGHT_RETRIES;
        }
      })
      .catch((error) => {
        if (cancelled) return;
        fetchedMissingFlightsRef.current.delete(selectedBranchId);
        const nextRetry = (missingFlightRetryCountRef.current[selectedBranchId] ?? 0) + 1;
        missingFlightRetryCountRef.current[selectedBranchId] = nextRetry;
        shouldRetry = nextRetry < MAX_MISSING_FLIGHT_RETRIES;
        console.error('[useBranchManager] Failed to fetch missing flights:', error);
      })
      .finally(() => {
        isFlightsRefreshingRef.current = false;
        if (cancelled || shouldRetry) {
          setSettingsRefreshTick((tick) => tick + 1);
        }
      });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- branchState object recreated each render; individual properties listed instead
  }, [
    branchState.selectedBranchId,
    branchState.tilesBranchId,
    branchState.selectedBranch,
    branchState.setTilesMap,
    branchState.setBranches,
    tripInputsOrigin,
    isGenerating,
    settingsRefreshTick,
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
