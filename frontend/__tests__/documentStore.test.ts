/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * documentStore Critical Path Tests
 *
 * Group 1: mergeEnvelope() — state merging logic for streaming envelopes
 * Group 3: commitTripInputs() — optimistic updates with conflict resolution
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));
vi.mock('@/state/chatStore', () => ({
  useChatStore: { getState: () => ({ resetChat: vi.fn() }) },
}));

import { apiFetch } from '@/lib/api';
import {
  DEFAULT_BOOKING_TYPES,
  DEFAULT_TRIP_INPUTS,
  markSettingDirty,
  useDocumentStore,
} from '@/state/documentStore';
import type { PlanDocumentData, PlanDocumentResponse } from '@/types/document';
import type { DayCard, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

const mockApiFetch = vi.mocked(apiFetch);

// ---------------------------------------------------------------------------
// Fixture Factories
// ---------------------------------------------------------------------------

function makeDoc(overrides: Partial<PlanDocumentData> = {}): PlanDocumentData {
  return {
    trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon' },
    branches: [],
    tiles: {},
    plan_view_state: 'S0_BOOTSTRAP',
    ...overrides,
  };
}

function makeTile(id: string, overrides: Partial<Tile> = {}): Tile {
  return {
    id,
    type: 'hotel',
    title: `Hotel ${id}`,
    currency: 'USD',
    deeplink_url: `https://example.com/${id}`,
    ...overrides,
  };
}

function makeSection(id: string, overrides: Partial<StrategySection> = {}): StrategySection {
  return {
    id,
    title: `Section ${id}`,
    specialist_type: 'hiking',
    principles: [],
    must_dos: [],
    optional_upgrades: [],
    logistics_notes: [],
    bullets: [],
    ...overrides,
  };
}

function makeDayCard(dayNumber: number): DayCard {
  return {
    day_number: dayNumber,
    label: `Day ${dayNumber}`,
    blocks: [],
  };
}

function mockResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

function makePatchResponse(
  version: number,
  docOverrides: Partial<PlanDocumentData> = {},
): PlanDocumentResponse {
  return {
    version,
    updated_by: 'user',
    updated_at: new Date().toISOString(),
    document: makeDoc(docOverrides),
  };
}

// ---------------------------------------------------------------------------
// Common Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  useDocumentStore.setState({
    version: 0,
    document: null,
    updatedBy: null,
    updatedAt: null,
    isCommitting: false,
    error: null,
    llmUpdatedFields: new Set(),
    preferredTileIds: new Set(),
    _lastPatchedTripInputs: null,
  });
  vi.clearAllMocks();
});

describe('hasAllRequiredFields', () => {
  it('returns false when destination is set but dates are missing', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Rome',
          start_date: null,
          end_date: null,
        },
      }),
    });

    expect(useDocumentStore.getState().hasAllRequiredFields()).toBe(false);
  });

  it('returns true only when destination and both dates are set', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Rome',
          start_date: '2026-03-01',
          end_date: '2026-03-07',
        },
      }),
    });

    expect(useDocumentStore.getState().hasAllRequiredFields()).toBe(true);
  });
});

describe('fetchDocument single-flight', () => {
  it('dedupes concurrent fetchDocument calls into one backend request', async () => {
    let resolveFetch: ((value: Response) => void) | null = null;
    mockApiFetch.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );

    const p1 = useDocumentStore.getState().fetchDocument();
    const p2 = useDocumentStore.getState().fetchDocument();

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(resolveFetch).not.toBeNull();

    const response = makePatchResponse(3, {
      trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Rome' },
      branches: [],
      tiles: {},
      plan_view_state: 'S0_BOOTSTRAP',
    });
    resolveFetch!(mockResponse(200, response));

    const [d1, d2] = await Promise.all([p1, p2]);
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(d1).toEqual(d2);
    expect(d1?.trip_inputs.destination).toBe('Rome');
  });
});

// ==========================================================================
// Group 1: mergeEnvelope
// ==========================================================================

describe('mergeEnvelope', () => {
  it('merges tiles additively when destination is unchanged', () => {
    const tileA = makeTile('a');
    const tileB = makeTile('b');
    useDocumentStore.setState({ document: makeDoc({ tiles: { a: tileA } }) });

    useDocumentStore.getState().mergeEnvelope({ tiles: { b: tileB } });

    const tiles = useDocumentStore.getState().document!.tiles;
    expect(Object.keys(tiles)).toHaveLength(2);
    expect(tiles['a']).toEqual(tileA);
    expect(tiles['b']).toEqual(tileB);
  });

  it('replaces strategy sections wholesale (envelope = full rebuild)', () => {
    // mergeEnvelope replaces sections entirely — this is correct behavior.
    // Preservation of content_added lives in setFromPlanResponse (incremental chat path).
    const existing = makeSection('hiking', {
      content_added: [{ title: 'Trail X', day: 1 }],
    });
    const incoming = makeSection('hiking', {
      content_added: [],
    });
    useDocumentStore.setState({
      document: makeDoc({ strategy_sections: [existing] }),
    });

    useDocumentStore.getState().mergeEnvelope({ strategy_sections: [incoming] });

    const sections = useDocumentStore.getState().document!.strategy_sections!;
    expect(sections).toHaveLength(1);
    expect(sections[0].content_added).toEqual([]);
  });

  it('blocks view state downgrade when day_cards exist', () => {
    useDocumentStore.setState({
      document: makeDoc({
        plan_view_state: 'S3_ITINERARY_READY',
        day_cards: [makeDayCard(1)],
      }),
    });

    useDocumentStore.getState().mergeEnvelope({
      plan_view_state: 'S2_STRATEGY_READY',
    });

    expect(useDocumentStore.getState().document!.plan_view_state).toBe('S3_ITINERARY_READY');
  });

  it('allows view state upgrade', () => {
    useDocumentStore.setState({
      document: makeDoc({
        plan_view_state: 'S2_STRATEGY_READY',
        day_cards: [makeDayCard(1)],
      }),
    });

    useDocumentStore.getState().mergeEnvelope({
      plan_view_state: 'S3_ITINERARY_READY',
    });

    expect(useDocumentStore.getState().document!.plan_view_state).toBe('S3_ITINERARY_READY');
  });

  it('allows lateral S3 transition to editing when day_cards exist', () => {
    useDocumentStore.setState({
      document: makeDoc({
        plan_view_state: 'S3_ITINERARY_READY',
        day_cards: [makeDayCard(1)],
      }),
    });

    useDocumentStore.getState().mergeEnvelope({
      plan_view_state: 'S3_EDITING',
    });

    expect(useDocumentStore.getState().document!.plan_view_state).toBe('S3_EDITING');
  });

  it('replaces day_cards when envelope provides them', () => {
    useDocumentStore.setState({
      document: makeDoc({
        day_cards: [makeDayCard(1), makeDayCard(2)],
      }),
    });

    const newCard = makeDayCard(3);
    useDocumentStore.getState().mergeEnvelope({ day_cards: [newCard] });

    const dayCards = useDocumentStore.getState().document!.day_cards!;
    expect(dayCards).toHaveLength(1);
    expect(dayCards[0].day_number).toBe(3);
  });

  it('produces no document content changes from an empty envelope', () => {
    const doc = makeDoc({
      tiles: { a: makeTile('a') },
      strategy_sections: [makeSection('hiking')],
    });
    useDocumentStore.setState({ document: doc });

    useDocumentStore.getState().mergeEnvelope({});

    const result = useDocumentStore.getState().document!;
    expect(result.tiles).toEqual(doc.tiles);
    expect(result.strategy_sections).toEqual(doc.strategy_sections);
    expect(result.trip_inputs).toEqual(doc.trip_inputs);
    expect(result.plan_view_state).toBe(doc.plan_view_state);
  });

  it('blocks destination change once destination is set', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon' },
      }),
    });

    useDocumentStore.getState().mergeEnvelope({
      trip_inputs: { destination: 'Tokyo', missing_fields: [] },
    });

    expect(useDocumentStore.getState().document!.trip_inputs.destination).toBe('Lisbon');
  });

  it('clears day_cards when dates change and envelope has no day_cards', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Lisbon',
          start_date: '2026-02-01',
          end_date: '2026-02-07',
        },
        day_cards: [makeDayCard(1), makeDayCard(2)],
      }),
    });

    useDocumentStore.getState().mergeEnvelope({
      trip_inputs: {
        start_date: '2026-02-01',
        end_date: '2026-02-10',
        missing_fields: [],
      },
    });

    expect(useDocumentStore.getState().document!.day_cards).toEqual([]);
  });

  it('clears browseableActivities when envelope sends an explicit empty list', () => {
    useDocumentStore.setState({
      document: makeDoc(),
      browseableActivities: [{ title: 'Cached activity' }],
    });

    useDocumentStore.getState().mergeEnvelope({ browseable_activities: [] });

    expect(useDocumentStore.getState().browseableActivities).toEqual([]);
  });
});

describe('setFromPlanResponse', () => {
  it('clears day_cards when dates change and graph returns no day_cards', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Lisbon',
          start_date: '2026-02-01',
          end_date: '2026-02-07',
        },
        day_cards: [makeDayCard(1), makeDayCard(2)],
      }),
    });

    const response = makePatchResponse(2, {
      trip_inputs: {
        ...DEFAULT_TRIP_INPUTS,
        destination: 'Lisbon',
        start_date: '2026-02-01',
        end_date: '2026-02-10',
      },
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    expect(useDocumentStore.getState().document!.day_cards).toEqual([]);
  });

  it('allows S3 itinerary to transition to S3 editing from graph response', () => {
    useDocumentStore.setState({
      document: makeDoc({
        plan_view_state: 'S3_ITINERARY_READY',
        day_cards: [makeDayCard(1), makeDayCard(2)],
      }),
    });

    const response = makePatchResponse(2, {
      plan_view_state: 'S3_EDITING',
      day_cards: [makeDayCard(1), makeDayCard(2)],
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    expect(useDocumentStore.getState().document!.plan_view_state).toBe('S3_EDITING');
  });

  it('clears preferredTileIds when backend returns an explicit empty list', () => {
    useDocumentStore.setState({
      document: makeDoc(),
      preferredTileIds: new Set(['tile-a']),
    });

    const response = makePatchResponse(2, { preferred_tile_ids: [] });
    useDocumentStore.getState().setFromPlanResponse(response);

    expect(useDocumentStore.getState().preferredTileIds.size).toBe(0);
  });

  it('clears browseableActivities when graph response returns an explicit empty list', () => {
    useDocumentStore.setState({
      document: makeDoc(),
      browseableActivities: [{ title: 'Cached activity' }],
    });

    const response = makePatchResponse(2, { browseable_activities: [] });
    useDocumentStore.getState().setFromPlanResponse(response);

    expect(useDocumentStore.getState().browseableActivities).toEqual([]);
  });

  it('prefers planner activity categories over local default categories', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Lisbon',
          booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' },
          activity_settings: { categories: ['cultural'], skill_level: null },
        },
      }),
    });

    const response = makePatchResponse(2, {
      trip_inputs: {
        ...DEFAULT_TRIP_INPUTS,
        destination: 'Lisbon',
        booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' },
        activity_settings: { categories: ['hiking'], skill_level: null },
      },
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    expect(useDocumentStore.getState().document!.trip_inputs.activity_settings?.categories).toEqual([
      'hiking',
    ]);
  });
});

describe('activity toggles', () => {
  it('keeps activities off when categories are populated', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Lisbon',
          booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' },
          activity_settings: { categories: ['yoga'], skill_level: null },
        },
      }),
    });

    useDocumentStore.getState().updateTripInputs({
      booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'off' },
    });

    const tripInputs = useDocumentStore.getState().document!.trip_inputs;
    expect(tripInputs.booking_types?.activities).toBe('off');
    expect(tripInputs.activity_settings?.categories).toEqual(['yoga']);
  });
});

// ==========================================================================
// Group 3: commitTripInputs
// ==========================================================================

describe('commitTripInputs', () => {
  // Track unresolved mock promises so afterEach can force-release the commit lock
  let pendingResolvers: Array<(v: Response) => void> = [];

  afterEach(async () => {
    // Force-resolve any hanging mocks so commitTripInputs finally{} releases lock
    pendingResolvers.forEach((r) =>
      r(mockResponse(200, makePatchResponse(99))),
    );
    pendingResolvers = [];
    // Flush microtasks so finally block runs releaseCommitLock()
    await new Promise((r) => setTimeout(r, 0));
    useDocumentStore.setState({ isCommitting: false });
  });

  it('applies optimistic update and merges backend response', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', budget: 3000 },
      })),
    );

    const result = await useDocumentStore.getState().commitTripInputs({ budget: 3000 });

    expect(result).toBe(true);
    expect(useDocumentStore.getState().version).toBe(2);
    expect(useDocumentStore.getState().isCommitting).toBe(false);
    expect(mockApiFetch).toHaveBeenCalledOnce();
  });

  it('prefers backend plan_view_state from PATCH response', async () => {
    useDocumentStore.setState({
      document: makeDoc({ plan_view_state: 'S3_ITINERARY_READY' }),
      version: 1,
    });

    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        plan_view_state: 'S2_STRATEGY_READY',
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', budget: 3000 },
      })),
    );

    const result = await useDocumentStore.getState().commitTripInputs({ budget: 3000 });

    expect(result).toBe(true);
    expect(useDocumentStore.getState().document!.plan_view_state).toBe('S2_STRATEGY_READY');
  });

  it('skips backend PATCH when updates are a no-op', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    const noopResult = await useDocumentStore.getState().commitTripInputs({ budget: null });
    expect(noopResult).toBe(true);
    expect(mockApiFetch).not.toHaveBeenCalled();

    // Lock should be released after no-op path.
    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', budget: 1500 },
      })),
    );
    const realResult = await useDocumentStore.getState().commitTripInputs({ budget: 1500 });
    expect(realResult).toBe(true);
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
  });

  it('retries with fresh version on 409 conflict', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    // Call 1: PATCH → 409
    mockApiFetch.mockResolvedValueOnce(mockResponse(409, {}));
    // Call 2: GET refetch → fresh doc at version 5
    mockApiFetch.mockResolvedValueOnce(mockResponse(200, makePatchResponse(5)));
    // Call 3: retry PATCH → success at version 6
    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(6, {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', adults: 4 },
      })),
    );

    const result = await useDocumentStore.getState().commitTripInputs({ adults: 4 });

    expect(result).toBe(true);
    expect(useDocumentStore.getState().version).toBe(6);
    expect(mockApiFetch).toHaveBeenCalledTimes(3);
  });

  it('rolls back on 500 failure', async () => {
    const originalBudget = DEFAULT_TRIP_INPUTS.budget; // null
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    mockApiFetch.mockResolvedValueOnce(mockResponse(500, {}));

    const result = await useDocumentStore.getState().commitTripInputs({ budget: 5000 });

    expect(result).toBe(false);
    expect(useDocumentStore.getState().document!.trip_inputs.budget).toBe(originalBudget);
    expect(useDocumentStore.getState().isCommitting).toBe(false);
    expect(useDocumentStore.getState().error).toBeTruthy();
  });

  it('blocks concurrent commits via mutex', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    // First PATCH: hangs until we manually resolve
    mockApiFetch.mockImplementationOnce(
      () => new Promise<Response>((resolve) => { pendingResolvers.push(resolve); }),
    );

    // Fire first commit (don't await yet)
    const p1 = useDocumentStore.getState().commitTripInputs({ budget: 1000 });
    // Let p1 acquire the lock (flush microtasks)
    await Promise.resolve();
    await Promise.resolve();

    // Second commit should be blocked
    const result2 = await useDocumentStore.getState().commitTripInputs({ budget: 2000 });
    expect(result2).toBe(false);

    // Clean up: resolve first PATCH so lock releases
    pendingResolvers.forEach((r) =>
      r(mockResponse(200, makePatchResponse(2))),
    );
    pendingResolvers = [];
    await p1;
  });
});

describe('ensureSettingsFlushed', () => {
  // Track unresolved mock promises so afterEach can force-release the commit lock
  let pendingResolvers: Array<(v: Response) => void> = [];

  afterEach(async () => {
    pendingResolvers.forEach((r) => r(mockResponse(200, makePatchResponse(99))));
    pendingResolvers = [];
    await new Promise((r) => setTimeout(r, 0));
    useDocumentStore.getState().reset();
    useDocumentStore.setState({ isCommitting: false });
  });

  it('skips when there are no dirty settings', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    await useDocumentStore.getState().ensureSettingsFlushed({
      requestId: 'req-none',
      sendCycleId: 'cycle-none',
    });

    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it('dedupes same payload hash within one send cycle', async () => {
    const originalCommitTripInputs = useDocumentStore.getState().commitTripInputs;
    const commitSpy = vi.fn().mockResolvedValue(true);
    try {
      useDocumentStore.setState({
        document: makeDoc({
          trip_inputs: {
            ...DEFAULT_TRIP_INPUTS,
            destination: 'Lisbon',
            hotel_settings: { min_stars: 5, amenities: [] },
          },
        }),
        version: 1,
        commitTripInputs: commitSpy,
      });
      markSettingDirty('hotel_settings');

      await useDocumentStore.getState().ensureSettingsFlushed({
        requestId: 'req-1',
        sendCycleId: 'cycle-1',
      });

      // Simulate same local state re-marked dirty in the same send cycle.
      markSettingDirty('hotel_settings');
      await useDocumentStore.getState().ensureSettingsFlushed({
        requestId: 'req-1b',
        sendCycleId: 'cycle-1',
      });

      expect(commitSpy).toHaveBeenCalledTimes(1);
    } finally {
      useDocumentStore.setState({ commitTripInputs: originalCommitTripInputs });
    }
  });

  it('waits for commit lock and avoids duplicate PATCH after in-flight commit', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });
    markSettingDirty('hotel_settings');

    mockApiFetch.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          pendingResolvers.push(resolve);
        }),
    );

    const commitPromise = useDocumentStore.getState().commitTripInputs({
      hotel_settings: { min_stars: 5, amenities: [] },
    });
    // Let commitTripInputs acquire lock
    await Promise.resolve();
    await Promise.resolve();

    const ensurePromise = useDocumentStore.getState().ensureSettingsFlushed({
      requestId: 'req-lock',
      sendCycleId: 'cycle-lock',
    });

    pendingResolvers.forEach((r) =>
      r(
        mockResponse(200, makePatchResponse(2, {
          trip_inputs: {
            ...DEFAULT_TRIP_INPUTS,
            destination: 'Lisbon',
            hotel_settings: { min_stars: 5, amenities: [] },
          },
        })),
      ),
    );
    pendingResolvers = [];

    await commitPromise;
    await ensurePromise;

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
  });
});
