import { act, renderHook } from '@testing-library/react';
import { useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  type PlanResultPayload,
  useBranchManager,
} from '@/components/layout/hooks/useBranchManager';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { DocumentBranch, GraphPlanResponse } from '@/types/document';
import type { Tile, TileSelection } from '@/types/tile';

const apiMocks = vi.hoisted(() => ({
  clearSessionLocalStorage: vi.fn(),
  refreshTiles: vi.fn(),
  resetSession: vi.fn(),
}));

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ...actual,
    clearSessionLocalStorage: apiMocks.clearSessionLocalStorage,
    refreshTiles: apiMocks.refreshTiles,
    resetSession: apiMocks.resetSession,
  };
});

vi.mock('zustand/traditional', () => ({
  useStoreWithEqualityFn: (
    store: {
      getState: () => unknown;
      subscribe: (listener: () => void) => () => void;
    },
    selector: (state: unknown) => unknown,
    equalityFn?: (a: unknown, b: unknown) => boolean
  ) => {
    const cacheRef = useRef<unknown>(undefined);

    return useSyncExternalStore(
      store.subscribe,
      () => {
        const nextSnapshot = selector(store.getState());
        if (
          cacheRef.current !== undefined &&
          (equalityFn
            ? equalityFn(cacheRef.current, nextSnapshot)
            : Object.is(cacheRef.current, nextSnapshot))
        ) {
          return cacheRef.current;
        }
        cacheRef.current = nextSnapshot;
        return nextSnapshot;
      },
      () => selector(store.getState())
    );
  },
}));

vi.mock('@/components/layout/hooks/useBranchState', () => ({
  useBranchState: () => {
    const [branches, setBranches] = useState<DocumentBranch[]>([]);
    const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
    const [tilesMap, setTilesMap] = useState<Record<string, Tile>>({});
    const [tilesBranchId, setTilesBranchId] = useState<string | null>(null);
    const [branchSelections, setBranchSelections] = useState<
      Record<string, TileSelection>
    >({});
    const abortTilesFetch = useMemo(() => vi.fn(), []);
    const handleBranchSelect = useMemo(() => vi.fn(), []);

    const selectedBranch = useMemo(
      () => branches.find((branch) => branch.id === selectedBranchId) ?? null,
      [branches, selectedBranchId]
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

    return {
      branches,
      selectedBranchId,
      tilesBranchId,
      branchSelections,
      selectedBranch,
      tiles,
      hasBranchesReady: branches.length > 0,
      abortTilesFetch,
      setBranches,
      setSelectedBranchId,
      setTilesMap,
      setTilesBranchId,
      setBranchSelections,
      handleBranchSelect,
    };
  },
}));

vi.mock('@/components/layout/hooks/useSessionHydration', () => ({
  clearSessionTimestamp: vi.fn(),
  useSessionHydration: () => ({ isHydratingSnapshot: false }),
}));

vi.mock('@/components/layout/hooks/useTileSelection', async () => {
  const actual = await vi.importActual<
    typeof import('@/components/layout/hooks/useTileSelection')
  >('@/components/layout/hooks/useTileSelection');
  return {
    ...actual,
    useTileSelection: () => ({
      activeBranchSelection: actual.EMPTY_TILE_SELECTION,
      handleTileSelection: vi.fn(),
    }),
  };
});

function buildBranch(overrides: Partial<DocumentBranch> = {}): DocumentBranch {
  return {
    id: 'branch_1',
    label: 'Primary',
    description: 'Primary branch',
    destination: 'Bali',
    origin: 'Rome',
    start_date: '2026-04-01',
    end_date: '2026-04-17',
    is_primary: true,
    ...overrides,
    tiles: {
      stays: [],
      flights: [],
      activities: [],
      ...overrides.tiles,
    },
    selections: {
      stay: null,
      flight: null,
      activities: [],
      ...overrides.selections,
    },
  };
}

function buildFlightTile(id = 'flight_1'): Tile {
  return {
    id,
    type: 'flight',
    title: 'Rome to Bali',
    subtitle: 'Direct',
    currency: 'USD',
    deeplink_url: 'https://example.com/flight',
  };
}

function buildGraphResponse(
  endDate: string,
  branch: DocumentBranch = buildBranch()
): GraphPlanResponse {
  return {
    version: 2,
    updated_by: 'planner',
    updated_at: '2026-03-15T20:30:00.000Z',
    changes_made: true,
    request_id: 'req_1',
    session_state: {},
    document: {
      trip_context_id: null,
      trip_inputs: {
        ...DEFAULT_TRIP_INPUTS,
        destination: 'Bali',
        origin: 'Rome',
        start_date: '2026-04-01',
        end_date: endDate,
        trip_duration: 17,
        adults: 1,
        children: 0,
        activity_settings: {
          ...DEFAULT_TRIP_INPUTS.activity_settings,
          categories: ['diving'],
        },
      },
      branches: [branch],
      tiles: {},
      strategy_sections: [],
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: [],
      executed_strategy_topics: [],
      pending_strategy_topics: [],
      open_decisions: [],
      suggestion_chips: [],
      suggested_responses: [],
      suggested_response_meta: [],
      ready_to_generate: true,
      ack_updates: [],
      conflicts: [],
      preferred_tile_ids: [],
      constraint_violations: [],
      constraints_validated: [],
      browseable_activities: [],
    },
  };
}

describe('useBranchManager result timing', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    apiMocks.refreshTiles.mockResolvedValue({
      tiles: [],
      refreshed_at: '2026-03-15T20:30:00.000Z',
      verticals_refreshed: [],
    });
    useDocumentStore.getState().reset();
    useDocumentStore.setState({
      version: 1,
      document: {
        trip_context_id: null,
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Bali',
          origin: 'Rome',
          start_date: '2026-04-01',
          end_date: '2026-04-07',
          trip_duration: 7,
          adults: 1,
          children: 0,
          activity_settings: {
            ...DEFAULT_TRIP_INPUTS.activity_settings,
            categories: ['diving'],
          },
        },
        branches: [],
        tiles: {},
        strategy_sections: [],
        plan_view_state: 'S3_ITINERARY_READY',
        day_cards: [],
      },
    } as never);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('applies updated trip inputs and branch state immediately even while the generating loader is still active', () => {
    const branch = buildBranch({
      tiles: { stays: [], flights: ['flight_existing'], activities: [] },
    });
    const flightTile = buildFlightTile('flight_existing');
    const payload: PlanResultPayload = {
      tripContextId: null,
      branches: [branch],
      tiles: { [flightTile.id]: flightTile },
      primaryBranchId: 'branch_1',
      tripInputs: buildGraphResponse('2026-04-17', branch).document.trip_inputs,
      readyToGenerate: true,
      response: buildGraphResponse('2026-04-17', branch),
    };

    const { result } = renderHook(() =>
      useBranchManager({
        chatPanelContainerRef: { current: null },
        onToast: vi.fn(),
        onChatKeyIncrement: vi.fn(),
        resetDraft: vi.fn(),
      })
    );

    act(() => {
      result.current.handleGeneratePlanStart();
    });

    expect(result.current.isGenerating).toBe(true);

    act(() => {
      result.current.handlePlanResult(payload);
    });

    expect(useDocumentStore.getState().document?.trip_inputs.end_date).toBe('2026-04-17');
    expect(useDocumentStore.getState().selectedBranchId).toBe('branch_1');
    expect(result.current.selectedBranchId).toBe('branch_1');
    expect(result.current.branches).toEqual([branch]);
    expect(result.current.hasBranchesReady).toBe(true);
    expect(result.current.isGenerating).toBe(true);

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(result.current.isGenerating).toBe(false);
  });

  it('allows missing-flight refreshes to run as soon as the plan result is visible, before the loader settles', async () => {
    const branch = buildBranch();
    const flightTile = buildFlightTile();
    apiMocks.refreshTiles.mockResolvedValue({
      tiles: [flightTile],
      refreshed_at: '2026-03-15T20:30:00.000Z',
      verticals_refreshed: ['flight'],
    });

    const payload: PlanResultPayload = {
      tripContextId: null,
      branches: [branch],
      tiles: {},
      primaryBranchId: 'branch_1',
      tripInputs: buildGraphResponse('2026-04-17', branch).document.trip_inputs,
      readyToGenerate: true,
      response: buildGraphResponse('2026-04-17', branch),
    };

    const { result } = renderHook(() =>
      useBranchManager({
        chatPanelContainerRef: { current: null },
        onToast: vi.fn(),
        onChatKeyIncrement: vi.fn(),
        resetDraft: vi.fn(),
      })
    );

    act(() => {
      result.current.handleGeneratePlanStart();
    });

    await act(async () => {
      result.current.handlePlanResult(payload);
      await Promise.resolve();
    });

    expect(result.current.isGenerating).toBe(true);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(apiMocks.refreshTiles).toHaveBeenCalledWith('branch_1', ['flight']);

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.branches[0]?.tiles.flights).toEqual(['flight_1']);
  });
});
