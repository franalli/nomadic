'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { resolveTabForTile, TAB_CONFIG, type TileTabKey } from '@/components/tiles/TilesGrid';
import { apiFetch, resetSession } from '@/lib/api';
import { saveTripSummary } from '@/lib/summary';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch, DocumentTripInputs, PlanDocumentResponse } from '@/types/document';
import type { TripSummaryPayload } from '@/types/summary';
import type { Tile, TileSelection } from '@/types/tile';

// Minimum time to show the generating loader for hype (in ms)
const GENERATING_MIN_DURATION_MS = 10000;

/** Shared empty selection to avoid re-creating object on each render */
const EMPTY_TILE_SELECTION: TileSelection = { activities: [] };

type BranchSelectionOverrides = {
  branch?: DocumentBranch;
  tripContextId?: number | null;
  errorMessageOverride?: string;
};

type TileCounts = Record<TileTabKey, number>;

const countTilesByTab = (tileList: Tile[]): TileCounts =>
  tileList.reduce(
    (acc, tile) => {
      const tab = resolveTabForTile(tile);
      acc[tab] += 1;
      return acc;
    },
    { stays: 0, flights: 0, activities: 0 } as TileCounts
  );

const summarizeTileCounts = (counts: TileCounts): string => {
  const parts: string[] = [];
  if (counts.stays) parts.push(`${counts.stays} stay${counts.stays === 1 ? '' : 's'}`);
  if (counts.flights)
    parts.push(`${counts.flights} flight${counts.flights === 1 ? '' : 's'}`);
  if (counts.activities)
    parts.push(`${counts.activities} activit${counts.activities === 1 ? 'y' : 'ies'}`);

  if (!parts.length) {
    return 'No live tiles yet—still hunting for stays, flights, and activities.';
  }
  return `Coverage: ${parts.join(' · ')}.`;
};

type SelectionCategory = 'stay' | 'flight' | 'activity';

const resolveSelectionCategory = (tile: Tile): SelectionCategory => {
  const tab = resolveTabForTile(tile);
  if (tab === 'flights') return 'flight';
  if (tab === 'activities') return 'activity';
  return 'stay';
};

const parseDateValue = (value: unknown): Date | null => {
  if (!value || typeof value !== 'string') return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const extractActivityRange = (tile: Tile): { start?: Date | null; end?: Date | null } => {
  const meta = (tile.meta as Record<string, unknown> | undefined) ?? {};
  const startRaw =
    meta.start_date ?? meta.date ?? meta.date_time ?? meta.start ?? meta.activity_date;
  const endRaw = meta.end_date ?? meta.end ?? meta.activity_end;
  const start = parseDateValue(startRaw);
  const end = parseDateValue(endRaw) ?? start;
  return { start, end };
};

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

const summarizeSelections = (selection?: TileSelection): string | null => {
  if (!selection) return null;
  const parts: string[] = [];
  if (selection.stay) {
    parts.push(`Stay: ${selection.stay.title}`);
  }
  if (selection.flight) {
    parts.push(`Flight: ${selection.flight.title}`);
  }
  if (selection.activities.length > 0) {
    const activityNames = selection.activities
      .map((act) => act.title)
      .slice(0, 3)
      .join(', ');
    const suffix = selection.activities.length > 3 ? ' +' : '';
    parts.push(`Activities: ${activityNames}${suffix}`);
  }

  if (!parts.length) return null;
  return `Locked choices — ${parts.join(' · ')}`;
};

/**
 * Convert ID-based BranchSelections (from server) to object-based TileSelection (for UI).
 * Missing tiles are skipped with a warning.
 */
const selectionsToTileSelection = (
  selections: { stay?: string | null; flight?: string | null; activities: string[] } | undefined,
  tilesMap: Record<string, Tile>
): TileSelection => {
  if (!selections) return EMPTY_TILE_SELECTION;
  const result: TileSelection = { activities: [] };

  if (selections.stay) {
    const stayTile = tilesMap[selections.stay];
    if (stayTile) {
      result.stay = stayTile;
    } else {
      console.warn(`selectionsToTileSelection: stay tile "${selections.stay}" not found in tilesMap`);
    }
  }

  if (selections.flight) {
    const flightTile = tilesMap[selections.flight];
    if (flightTile) {
      result.flight = flightTile;
    } else {
      console.warn(`selectionsToTileSelection: flight tile "${selections.flight}" not found in tilesMap`);
    }
  }

  for (const activityId of selections.activities) {
    const activityTile = tilesMap[activityId];
    if (activityTile) {
      result.activities.push(activityTile);
    } else {
      console.warn(`selectionsToTileSelection: activity tile "${activityId}" not found in tilesMap`);
    }
  }

  return result;
};

export interface BranchManagerOptions {
  tripInputs: DocumentTripInputs;
  chatPanelContainerRef: React.RefObject<HTMLDivElement | null>;
  onToast: (message: string) => void;
  onChatKeyIncrement: () => void;
  resetDraft: () => void;
}

export interface PlanResultPayload {
  tripContextId: number | null;
  branches: DocumentBranch[];
  tiles: Record<string, Tile>;
  primaryBranchId: string | null;
  tripInputs?: DocumentTripInputs | null;
  readyToGenerate?: boolean;
  response?: PlanDocumentResponse;
}

export interface BranchManagerState {
  branches: DocumentBranch[];
  selectedBranchId: string | null;
  tilesMap: Record<string, Tile>;
  tilesBranchId: string | null;
  branchTileNotes: Record<string, string>;
  branchTileCounts: Record<string, TileCounts>;
  branchTabNotes: Record<string, string>;
  branchSelections: Record<string, TileSelection>;
  isGenerating: boolean;
  isHydratingSnapshot: boolean;
  isResettingSession: boolean;
}

export interface BranchManagerComputed {
  selectedBranch: DocumentBranch | null;
  activeBranchSelection: TileSelection;
  branchesWithTileNotes: DocumentBranch[];
  tiles: Tile[];
  readyToGenerate: boolean;
  hasBranchesReady: boolean;
}

export interface BranchManagerActions {
  setBranches: React.Dispatch<React.SetStateAction<DocumentBranch[]>>;
  setSelectedBranchId: React.Dispatch<React.SetStateAction<string | null>>;
  handleBranchSelect: (branchId: string, overrides?: BranchSelectionOverrides) => Promise<void>;
  handleClearContext: () => void;
  handleStartNewSession: () => Promise<void>;
  handlePlanResult: (result: PlanResultPayload) => void;
  handleTileSelection: (tile: Tile) => void;
  handleTilesTabChange: (tab: TileTabKey, filteredTiles: Tile[]) => void;
  handleBookTrip: (branchId: string) => void;
  handleGeneratePlanStart: () => void;
}

export type UseBranchManagerReturn = BranchManagerState &
  BranchManagerComputed &
  BranchManagerActions;

export function useBranchManager(options: BranchManagerOptions): UseBranchManagerReturn {
  const {
    tripInputs,
    chatPanelContainerRef,
    onToast,
    onChatKeyIncrement,
    resetDraft,
  } = options;

  const documentStore = useDocumentStore();

  // State
  const [branches, setBranches] = useState<DocumentBranch[]>([]);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [tilesMap, setTilesMap] = useState<Record<string, Tile>>({});
  const [tilesBranchId, setTilesBranchId] = useState<string | null>(null);
  const [branchTileNotes, setBranchTileNotes] = useState<Record<string, string>>({});
  const [branchTileCounts, setBranchTileCounts] = useState<Record<string, TileCounts>>({});
  const [branchTabNotes, setBranchTabNotes] = useState<Record<string, string>>({});
  const [branchSelections, setBranchSelections] = useState<Record<string, TileSelection>>({});
  const [isGenerating, setIsGenerating] = useState(false);
  const [isHydratingSnapshot, setIsHydratingSnapshot] = useState(true);
  const [isResettingSession, setIsResettingSession] = useState(false);

  // Refs
  const generatingStartTimeRef = useRef<number | null>(null);
  const generatingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const tilesFetchControllerRef = useRef<AbortController | null>(null);

  // Computed values
  const readyToGenerate = useMemo(() => {
    const hasAllFields = documentStore.hasAllRequiredFields();
    const noBranches = branches.length === 0;
    return hasAllFields && noBranches;
  }, [documentStore, branches.length]);

  const selectedBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) ?? null,
    [branches, selectedBranchId]
  );

  const activeBranchSelection = useMemo(
    () =>
      selectedBranchId
        ? (branchSelections[selectedBranchId] ?? EMPTY_TILE_SELECTION)
        : EMPTY_TILE_SELECTION,
    [branchSelections, selectedBranchId]
  );

  const branchesWithTileNotes = useMemo(
    () =>
      branches.map((branch) => {
        const note = branchTileNotes[branch.id];
        const baseDescription = (branch.description ?? '').trim();
        const mergedDescription = [baseDescription, note]
          .filter(Boolean)
          .join(baseDescription && note ? ' ' : '');
        return { ...branch, description: mergedDescription };
      }),
    [branchTileNotes, branches]
  );

  const tiles = useMemo(() => {
    if (!selectedBranch) return [];
    const tileIds = [
      ...selectedBranch.tiles.stays,
      ...selectedBranch.tiles.flights,
      ...selectedBranch.tiles.activities,
    ];
    return tileIds
      .map((id) => tilesMap[id])
      .filter((tile): tile is Tile => tile !== undefined);
  }, [selectedBranch, tilesMap]);

  const hasBranchesReady = branches.length > 0;

  // Handlers
  const abortTilesFetch = useCallback(() => {
    if (tilesFetchControllerRef.current) {
      tilesFetchControllerRef.current.abort();
      tilesFetchControllerRef.current = null;
    }
  }, []);

  const handleBranchSelect = useCallback(
    async (branchId: string, overrides?: BranchSelectionOverrides) => {
      abortTilesFetch();
      const controller = new AbortController();
      tilesFetchControllerRef.current = controller;

      const branchChanged = branchId !== selectedBranchId;
      setSelectedBranchId(branchId);
      setTilesBranchId(null);
      if (branchChanged) {
        setBranchSelections((prev) => {
          if (prev[branchId]) return prev;
          return { ...prev, [branchId]: EMPTY_TILE_SELECTION };
        });
      }
      const branch = overrides?.branch ?? branches.find((b) => b.id === branchId);
      if (!branch) return;
      setBranchTileNotes((prev) => ({
        ...prev,
        [branchId]: 'Refreshing booking options for this suggestion.',
      }));
      setBranchTileCounts((prev) => {
        const next = { ...prev };
        delete next[branchId];
        return next;
      });
      setBranchTabNotes((prev) => {
        const next = { ...prev };
        delete next[branchId];
        return next;
      });

      const errorMessageOverride = overrides?.errorMessageOverride;

      try {
        const res = await apiFetch(
          `/v1/document/tiles/${encodeURIComponent(branchId)}`,
          {
            method: 'POST',
            signal: controller.signal,
          }
        );

        if (!res.ok) {
          console.error('Failed to fetch tiles for branch', res.status);
          onToast(
            errorMessageOverride ??
              'Unable to refresh options for that suggestion. Please try again.'
          );
          return;
        }

        const data: PlanDocumentResponse = await res.json();
        if (controller.signal.aborted) return;

        // Update state from the document response
        setBranches(data.document.branches);
        setTilesMap(data.document.tiles);
        setTilesBranchId(branchId);
      } catch (error) {
        if ((error as DOMException).name === 'AbortError') return;
        console.error('Failed to fetch tiles for branch', error);
        onToast(
          errorMessageOverride ??
            'Unable to refresh options for that suggestion. Please try again.'
        );
      } finally {
        if (tilesFetchControllerRef.current === controller) {
          tilesFetchControllerRef.current = null;
        }
      }
    },
    [abortTilesFetch, branches, selectedBranchId, onToast]
  );

  const handleClearContext = useCallback(() => {
    abortTilesFetch();
    // Clear any pending generating state
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
    setIsGenerating(false);
    generatingStartTimeRef.current = null;

    setBranches([]);
    setSelectedBranchId(null);
    setTilesMap({});
    setTilesBranchId(null);
    setBranchTileNotes({});
    setBranchTileCounts({});
    setBranchTabNotes({});
    setBranchSelections({});
    // Reset the draft to defaults (store will be reset separately)
    resetDraft();
    // Reset the store
    documentStore.reset();
    // Increment chat key to reset the panel
    onChatKeyIncrement();
  }, [abortTilesFetch, documentStore, resetDraft, onChatKeyIncrement]);

  const handleStartNewSession = useCallback(async () => {
    abortTilesFetch();
    setIsResettingSession(true);
    let didResetServerState = false;

    try {
      const res = await resetSession();
      didResetServerState = res.ok;
    } catch (error) {
      console.error('Failed to reset planning session', error);
    } finally {
      handleClearContext();
      setIsResettingSession(false);
      // Scroll to chat panel after reset
      setTimeout(() => {
        if (chatPanelContainerRef.current) {
          chatPanelContainerRef.current.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
          });
          // Focus the input if it exists
          const input = chatPanelContainerRef.current.querySelector(
            'input[type="text"]'
          ) as HTMLInputElement;
          if (input) {
            input.focus();
          }
        }
      }, 100);
    }

    onToast(
      didResetServerState
        ? 'Started a fresh planning session.'
        : 'Cleared your local planner, but the previous session may reappear if you refresh.'
    );
  }, [abortTilesFetch, handleClearContext, chatPanelContainerRef, onToast]);

  // Helper to finalize the generating state and show branches
  const finalizeGenerating = useCallback(
    (result: PlanResultPayload | null) => {
      if (!result) return;

      if (result.response) {
        documentStore.setFromPlanResponse(result.response);
      }

      setBranches(result.branches);
      setTilesMap(result.tiles);
      setTilesBranchId(result.primaryBranchId);
      setBranchTileNotes((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, string> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) next[id] = prev[id];
        });
        return next;
      });
      setBranchTileCounts((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, TileCounts> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) next[id] = prev[id];
        });
        return next;
      });
      setBranchTabNotes((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, string> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) next[id] = prev[id];
        });
        return next;
      });
      setBranchSelections(() => {
        const next: Record<string, TileSelection> = {};
        result.branches.forEach((branch) => {
          next[branch.id] = selectionsToTileSelection(branch.selections, result.tiles);
        });
        return next;
      });
      setSelectedBranchId(result.primaryBranchId);

      // Clear generating state
      setIsGenerating(false);
      generatingStartTimeRef.current = null;
    },
    [documentStore]
  );

  const handlePlanResult = useCallback(
    (result: PlanResultPayload) => {
      const hasBranchesInResult = result.branches.length > 0;

      // If we're in generating state and branches were returned, apply minimum loading time
      if (isGenerating && hasBranchesInResult && generatingStartTimeRef.current) {
        const elapsed = Date.now() - generatingStartTimeRef.current;
        const remaining = GENERATING_MIN_DURATION_MS - elapsed;

        if (remaining > 0) {
          // Wait for the minimum time, then finalize
          generatingTimerRef.current = setTimeout(() => {
            finalizeGenerating(result);
          }, remaining);
          return;
        }

        // Minimum time already passed, finalize immediately
        finalizeGenerating(result);
        return;
      }

      // Not in generating state or no branches - process normally

      // If we have a full response, update the store (single source of truth)
      if (result.response) {
        documentStore.setFromPlanResponse(result.response);
      }

      setBranches(result.branches);
      setTilesMap(result.tiles);
      setTilesBranchId(result.primaryBranchId);
      setBranchTileNotes((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, string> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) {
            next[id] = prev[id];
          }
        });
        return next;
      });
      setBranchTileCounts((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, TileCounts> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) {
            next[id] = prev[id];
          }
        });
        return next;
      });
      setBranchTabNotes((prev) => {
        const allowedIds = new Set(result.branches.map((b) => b.id));
        const next: Record<string, string> = {};
        allowedIds.forEach((id) => {
          if (prev[id]) {
            next[id] = prev[id];
          }
        });
        return next;
      });
      setBranchSelections(() => {
        const next: Record<string, TileSelection> = {};
        result.branches.forEach((branch) => {
          next[branch.id] = selectionsToTileSelection(branch.selections, result.tiles);
        });
        return next;
      });
      setSelectedBranchId(result.primaryBranchId);

      // If we were generating but got an error (no branches), clear the generating state
      if (isGenerating && !hasBranchesInResult) {
        setIsGenerating(false);
        generatingStartTimeRef.current = null;
        if (generatingTimerRef.current) {
          clearTimeout(generatingTimerRef.current);
          generatingTimerRef.current = null;
        }
      }
    },
    [documentStore, isGenerating, finalizeGenerating]
  );

  const buildBranchNote = useCallback(
    (
      branchId: string,
      noteOptions?: {
        tabNote?: string;
        countsOverride?: TileCounts;
        selectionOverride?: TileSelection;
      }
    ) => {
      const selectionNote = summarizeSelections(
        noteOptions?.selectionOverride ?? branchSelections[branchId]
      );
      const counts = noteOptions?.countsOverride ?? branchTileCounts[branchId];
      const countsNote = counts ? summarizeTileCounts(counts) : null;
      const tabNote = noteOptions?.tabNote ?? branchTabNotes[branchId];
      return [selectionNote, countsNote, tabNote].filter(Boolean).join(' ');
    },
    [branchSelections, branchTabNotes, branchTileCounts]
  );

  const handleTileSelection = useCallback(
    (tile: Tile) => {
      const branchId = tilesBranchId ?? selectedBranchId;
      if (!branchId) return;

      // Compute the new selection and whether it's a deselect outside of setState
      const current = branchSelections[branchId] ?? EMPTY_TILE_SELECTION;
      const nextSelection: TileSelection = {
        stay: current.stay,
        flight: current.flight,
        activities: [...current.activities],
      };

      const category = resolveSelectionCategory(tile);
      let isDeselect = false;

      if (category === 'stay') {
        isDeselect = Boolean(current.stay && current.stay.id === tile.id);
        nextSelection.stay = isDeselect ? undefined : tile;
      } else if (category === 'flight') {
        isDeselect = Boolean(current.flight && current.flight.id === tile.id);
        nextSelection.flight = isDeselect ? undefined : tile;
      } else {
        const existingIdx = nextSelection.activities.findIndex(
          (activity) => activity.id === tile.id
        );
        if (existingIdx >= 0) {
          isDeselect = true;
          nextSelection.activities.splice(existingIdx, 1);
        } else {
          const pruned = nextSelection.activities.filter(
            (activity) => !activitiesOverlap(activity, tile)
          );
          nextSelection.activities = [...pruned, tile];
        }
      }

      // Update local state synchronously
      setBranchSelections((prev) => ({ ...prev, [branchId]: nextSelection }));

      setBranchTileNotes((prevNotes) => ({
        ...prevNotes,
        [branchId]: buildBranchNote(branchId, { selectionOverride: nextSelection }),
      }));

      // Sync to document store asynchronously (fire-and-forget, outside of render)
      const tileType = category === 'stay' ? 'stay' : category === 'flight' ? 'flight' : 'activity';
      if (isDeselect) {
        documentStore.deselectTile(branchId, tileType, tile.id).catch((err) => {
          console.error('Failed to sync tile deselection:', err);
          onToast('Failed to save selection. Please try again.');
        });
      } else {
        documentStore.selectTile(branchId, tile.id, tileType).catch((err) => {
          console.error('Failed to sync tile selection:', err);
          onToast('Failed to save selection. Please try again.');
        });
      }
    },
    [branchSelections, buildBranchNote, documentStore, selectedBranchId, tilesBranchId, onToast]
  );

  const describeTileSelection = useCallback((tab: TileTabKey, filteredTiles: Tile[]) => {
    const label = TAB_CONFIG[tab].label;
    if (!filteredTiles.length) {
      return `${label}: no live options yet for this branch. I will keep it flexible until new results arrive.`;
    }

    const priceValues = filteredTiles
      .map((tile) => tile.price_estimate)
      .filter((value): value is number => typeof value === 'number');
    const currency = filteredTiles.find((tile) => tile.currency)?.currency ?? '';
    const priceSummary = (() => {
      if (!priceValues.length) return '';
      const min = Math.min(...priceValues);
      const max = Math.max(...priceValues);
      const formattedMin = Math.round(min).toLocaleString();
      const formattedMax = Math.round(max).toLocaleString();
      if (min === max) return `${formattedMin} ${currency}`.trim();
      return `${formattedMin}–${formattedMax} ${currency}`.trim();
    })();

    const parts: string[] = [];
    parts.push(
      `${label} tuned: ${filteredTiles.length} option${filteredTiles.length === 1 ? '' : 's'}.`
    );
    if (priceSummary) {
      parts.push(`Price band around ${priceSummary}.`);
    }
    const highlightTitle = filteredTiles[0]?.title;
    if (highlightTitle) {
      parts.push(`Highlighting ${highlightTitle}.`);
    }

    return parts.join(' ');
  }, []);

  const handleTilesTabChange = useCallback(
    (tab: TileTabKey, filteredTiles: Tile[]) => {
      if (!selectedBranchId) return;
      if (!tilesBranchId || tilesBranchId !== selectedBranchId) return;
      const tabNote = describeTileSelection(tab, filteredTiles);
      setBranchTabNotes((prev) => ({ ...prev, [selectedBranchId]: tabNote }));
      setBranchTileNotes((prev) => {
        const selectionNote = summarizeSelections(branchSelections[selectedBranchId]);
        const counts = branchTileCounts[selectedBranchId];
        const countsNote = counts ? summarizeTileCounts(counts) : null;
        const note = [selectionNote, countsNote, tabNote].filter(Boolean).join(' ');
        return { ...prev, [selectedBranchId]: note };
      });
    },
    [branchSelections, branchTileCounts, describeTileSelection, selectedBranchId, tilesBranchId]
  );

  const handleBookTrip = useCallback(
    (branchId: string) => {
      const branch = branches.find((b) => b.id === branchId);
      if (!branch) {
        console.error('handleBookTrip: branch not found', branchId);
        return;
      }
      const selection = branchSelections[branchId] ?? EMPTY_TILE_SELECTION;
      const payload: TripSummaryPayload = {
        branch,
        selection: {
          stay: selection.stay,
          flight: selection.flight,
          activities: selection.activities ?? [],
        },
        tiles: tilesBranchId === branchId ? tiles : [],
        note: branchTileNotes[branchId] ?? null,
        generatedAt: new Date().toISOString(),
      };
      saveTripSummary(payload);
      window.location.href = '/summary';
    },
    [branchSelections, branchTileNotes, branches, tiles, tilesBranchId]
  );

  const handleGeneratePlanStart = useCallback(() => {
    setIsGenerating(true);
    generatingStartTimeRef.current = Date.now();
    // Clear any existing timer
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
  }, []);

  // Effects

  // Hydrate session document on mount
  useEffect(() => {
    let cancelled = false;

    async function hydrateSessionDocument() {
      try {
        setIsHydratingSnapshot(true);

        // Use the store to fetch and cache the document (single source of truth)
        // fetchDocument returns the document directly so we don't access stale closure state
        const doc = await documentStore.fetchDocument();
        if (cancelled) return;

        if (!doc) return;

        if (!doc.branches.length) return;

        setBranches(doc.branches);
        setTilesMap(doc.tiles);

        // Restore branchSelections from server-persisted selections
        const restoredSelections: Record<string, TileSelection> = {};
        for (const branch of doc.branches) {
          restoredSelections[branch.id] = selectionsToTileSelection(branch.selections, doc.tiles);
        }
        setBranchSelections(restoredSelections);

        const primaryBranch = doc.branches.find((b) => b.is_primary);
        const fallbackBranchId = primaryBranch?.id ?? doc.branches[0].id;

        setSelectedBranchId(fallbackBranchId);
        setTilesBranchId(fallbackBranchId);

        // Check if the primary branch has tiles, if not fetch them
        const hasTilesForBranch =
          primaryBranch &&
          (primaryBranch.tiles.stays.length > 0 ||
            primaryBranch.tiles.flights.length > 0 ||
            primaryBranch.tiles.activities.length > 0);

        if (!hasTilesForBranch && fallbackBranchId) {
          const overrides: BranchSelectionOverrides = {
            branch: primaryBranch ?? doc.branches[0],
            tripContextId: doc.trip_context_id ?? null,
            errorMessageOverride:
              'We restored your suggestions but could not refresh options automatically. Select a suggestion to try again.',
          };

          // Note: handleBranchSelect is stable because branches is empty at this point
          // We need to call it with the doc.branches directly
          const controller = new AbortController();
          tilesFetchControllerRef.current = controller;

          setSelectedBranchId(fallbackBranchId);
          setTilesBranchId(null);
          setBranchTileNotes((prev) => ({
            ...prev,
            [fallbackBranchId]: 'Refreshing booking options for this suggestion.',
          }));

          try {
            const res = await apiFetch(
              `/v1/document/tiles/${encodeURIComponent(fallbackBranchId)}`,
              {
                method: 'POST',
                signal: controller.signal,
              }
            );

            if (!res.ok) {
              console.error('Failed to fetch tiles for branch', res.status);
              onToast(
                overrides.errorMessageOverride ??
                  'Unable to refresh options for that suggestion. Please try again.'
              );
              return;
            }

            const data: PlanDocumentResponse = await res.json();
            if (controller.signal.aborted) return;

            setBranches(data.document.branches);
            setTilesMap(data.document.tiles);
            setTilesBranchId(fallbackBranchId);
          } catch (error) {
            if ((error as DOMException).name === 'AbortError') return;
            console.error('Failed to fetch tiles for branch', error);
            onToast(
              overrides.errorMessageOverride ??
                'Unable to refresh options for that suggestion. Please try again.'
            );
          } finally {
            if (tilesFetchControllerRef.current === controller) {
              tilesFetchControllerRef.current = null;
            }
          }
        }
      } catch (error) {
        console.error('Failed to hydrate session document', error);
        onToast(
          'Unable to reload your previous session. You can still plan a new trip.'
        );
      } finally {
        setIsHydratingSnapshot(false);
      }
    }

    hydrateSessionDocument();

    return () => {
      cancelled = true;
    };
    // We intentionally run this only once on mount to restore the last session document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup tiles fetch on unmount
  useEffect(
    () => () => {
      abortTilesFetch();
    },
    [abortTilesFetch]
  );

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (generatingTimerRef.current) {
        clearTimeout(generatingTimerRef.current);
      }
    };
  }, []);

  // Update tile counts and notes when tiles change
  useEffect(() => {
    if (!tilesBranchId) return;
    const counts = countTilesByTab(tiles);
    setBranchTileCounts((prev) => ({ ...prev, [tilesBranchId]: counts }));
    setBranchTileNotes((prev) => {
      const selectionNote = summarizeSelections(branchSelections[tilesBranchId]);
      const countsNote = summarizeTileCounts(counts);
      const tabNote = branchTabNotes[tilesBranchId];
      const note = [selectionNote, countsNote, tabNote].filter(Boolean).join(' ');
      return { ...prev, [tilesBranchId]: note };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tiles, tilesBranchId]);

  // Sync branch notes
  useEffect(() => {
    const branchIds = new Set([
      ...branches.map((b) => b.id),
      ...Object.keys(branchSelections),
      ...Object.keys(branchTileCounts),
      ...Object.keys(branchTabNotes),
    ]);
    if (branchIds.size === 0) return;

    setBranchTileNotes((prev) => {
      let didChange = false;
      const next = { ...prev };
      branchIds.forEach((branchId) => {
        const note = buildBranchNote(branchId);
        if (note) {
          if (next[branchId] !== note) {
            next[branchId] = note;
            didChange = true;
          }
        } else if (next[branchId]) {
          delete next[branchId];
          didChange = true;
        }
      });
      Object.keys(next).forEach((branchId) => {
        if (!branchIds.has(branchId)) {
          delete next[branchId];
          didChange = true;
        }
      });
      return didChange ? next : prev;
    });
  }, [branchSelections, branches, branchTabNotes, branchTileCounts, buildBranchNote]);

  return {
    // State
    branches,
    selectedBranchId,
    /** @internal Kept for debugging and potential future use */
    tilesMap,
    tilesBranchId,
    branchTileNotes,
    branchTileCounts,
    /** @internal Kept for debugging and potential future use */
    branchTabNotes,
    branchSelections,
    isGenerating,
    isHydratingSnapshot,
    /** @internal Kept for debugging and potential future use */
    isResettingSession,
    // Computed
    selectedBranch,
    activeBranchSelection,
    branchesWithTileNotes,
    tiles,
    readyToGenerate,
    hasBranchesReady,
    // Actions
    setBranches,
    setSelectedBranchId,
    handleBranchSelect,
    /** @internal Kept for API completeness - called internally but may be useful for debugging */
    handleClearContext,
    handleStartNewSession,
    handlePlanResult,
    handleTileSelection,
    handleTilesTabChange,
    handleBookTrip,
    handleGeneratePlanStart,
  };
}
