/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * documentStore Critical Path Tests
 *
 * Group 1: mergeEnvelope() — state merging logic for streaming envelopes
 * Group 3: commitTripInputs() — optimistic updates with conflict resolution
 */

import type { MockInstance } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));
vi.mock('@/state/chatStore', () => ({
  useChatStore: { getState: () => ({ resetChat: vi.fn() }) },
}));

const mockApiFetch = vi.mocked(apiFetch);
let consoleLogSpy: MockInstance;

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
  consoleLogSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  useDocumentStore.setState({
    version: 0,
    document: null,
    updatedBy: null,
    updatedAt: null,
    generation: null,
    currentRunId: null,
    abortController: null,
    isCommitting: false,
    error: null,
    llmUpdatedFields: new Set(),
    preferredTileIds: new Set(),
    _lastPatchedTripInputs: null,
    // Sticky UI guard — reset between tests so it never leaks (e.g. into the
    // bootstrap-seeding test, which expects ['cultural'] with the guard false).
    hasEverHadPlanContent: false,
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

describe('generation lifecycle', () => {
  it('clears stale generation state when completeGeneration runs', () => {
    useDocumentStore.setState({
      generation: { active: true, stage: 'structure', message: 'Searching' },
      currentRunId: 'run-1',
    });

    useDocumentStore.getState().completeGeneration();

    expect(useDocumentStore.getState().currentRunId).toBeNull();
    expect(useDocumentStore.getState().generation).toBeNull();
  });

  it('clears stale generation state when abortGeneration runs', () => {
    useDocumentStore.setState({
      generation: { active: true, stage: 'itinerary', message: 'Building' },
      currentRunId: 'run-2',
      abortController: new AbortController(),
    });

    useDocumentStore.getState().abortGeneration();

    expect(useDocumentStore.getState().currentRunId).toBeNull();
    expect(useDocumentStore.getState().abortController).toBeNull();
    expect(useDocumentStore.getState().generation).toBeNull();
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

  it('bootstraps a minimal document when a partial envelope arrives before any document exists', () => {
    useDocumentStore.setState({ document: null });

    useDocumentStore.getState().mergeEnvelope({
      trip_inputs: {
        destination: 'Bali',
        start_date: '2026-04-01',
        end_date: '2026-04-07',
        missing_fields: [],
      },
      strategy_sections: [makeSection('diving', { specialist_type: 'diving' })],
      day_cards: [makeDayCard(1)],
    });

    const doc = useDocumentStore.getState().document;
    expect(doc).not.toBeNull();
    expect(doc!.trip_inputs.destination).toBe('Bali');
    expect(doc!.strategy_sections).toHaveLength(1);
    expect(doc!.day_cards).toHaveLength(1);
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

  it('logs price-only tile changes as a real tile delta', () => {
    const currentFlight = makeTile('flight-1', {
      type: 'flight',
      title: 'Etihad Airways - 2 stops',
      price_estimate: 391,
    });
    useDocumentStore.setState({
      document: makeDoc({
        tiles: { 'flight-1': currentFlight },
      }),
    });

    const response = makePatchResponse(2, {
      tiles_replaced: true,
      tiles: {
        'flight-1': makeTile('flight-1', {
          type: 'flight',
          title: 'Etihad Airways - 2 stops',
          price_estimate: 405,
        }),
      },
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    const diagLine = consoleLogSpy.mock.calls
      .map((call) => String(call[0]))
      .find((line) => line.includes('[DIAG:TILE_DELTA]') && line.includes('changed:'));

    expect(diagLine).toContain('changed: true');
  });

  it('drops a backend-removed strategy section when tiles_replaced is true (NL removal)', () => {
    // Same-destination "no diving" removal turn: backend prunes the diving section and
    // sets tiles_replaced=true. The additive re-push must NOT resurrect the dropped section.
    const tripInputs = {
      ...DEFAULT_TRIP_INPUTS,
      destination: 'Bali',
      start_date: '2026-04-01',
      end_date: '2026-04-07',
    };
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: tripInputs,
        strategy_sections: [
          makeSection('diving', { specialist_type: 'diving' }),
          makeSection('hiking', { specialist_type: 'hiking' }),
        ],
        plan_view_state: 'S2_STRATEGY_READY',
      }),
      version: 1,
    });

    const response = makePatchResponse(2, {
      trip_inputs: structuredClone(tripInputs),
      // Backend dropped diving — only hiking remains in the authoritative set.
      strategy_sections: [makeSection('hiking', { specialist_type: 'hiking' })],
      tiles_replaced: true,
      plan_view_state: 'S2_STRATEGY_READY',
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    const sections = useDocumentStore.getState().document!.strategy_sections!;
    expect(sections).toHaveLength(1);
    expect(sections.map((s) => s.specialist_type)).toEqual(['hiking']);
    expect(sections.some((s) => s.specialist_type === 'diving')).toBe(false);
  });

  it('preserves cached strategy sections on a lightweight route when tiles_replaced is falsy', () => {
    // Origin/settings change: backend re-emits a subset of sections without tiles_replaced.
    // The additive re-push must keep cached specialists that are absent from the response.
    const tripInputs = {
      ...DEFAULT_TRIP_INPUTS,
      destination: 'Bali',
      start_date: '2026-04-01',
      end_date: '2026-04-07',
    };
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: tripInputs,
        strategy_sections: [
          makeSection('diving', { specialist_type: 'diving' }),
          makeSection('hiking', { specialist_type: 'hiking' }),
        ],
        plan_view_state: 'S2_STRATEGY_READY',
      }),
      version: 1,
    });

    const response = makePatchResponse(2, {
      trip_inputs: structuredClone(tripInputs),
      // Lightweight route only re-emits hiking; tiles_replaced is absent/falsy.
      strategy_sections: [makeSection('hiking', { specialist_type: 'hiking' })],
      plan_view_state: 'S2_STRATEGY_READY',
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    const sections = useDocumentStore.getState().document!.strategy_sections!;
    expect(sections).toHaveLength(2);
    expect(sections.map((s) => s.specialist_type).sort()).toEqual(['diving', 'hiking']);
  });

  it('preserves heavy subtree references when complete payload repeats already-merged data', () => {
    const tripInputs = {
      ...DEFAULT_TRIP_INPUTS,
      destination: 'Bali',
      start_date: '2026-04-01',
      end_date: '2026-04-07',
      activity_settings: { categories: ['diving'], skill_level: null, day_preferences: {} },
    };
    const dayCards = [makeDayCard(1), makeDayCard(2)];
    const strategySections = [makeSection('diving', { specialist_type: 'diving' })];
    const tiles = { 'flight-1': makeTile('flight-1', { type: 'flight' }) };

    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: tripInputs,
        day_cards: dayCards,
        strategy_sections: strategySections,
        tiles,
        plan_view_state: 'S3_ITINERARY_READY',
      }),
      version: 1,
    });

    const response = makePatchResponse(2, {
      trip_inputs: structuredClone(tripInputs),
      day_cards: structuredClone(dayCards),
      strategy_sections: structuredClone(strategySections),
      tiles: structuredClone(tiles),
      tiles_replaced: true,
      plan_view_state: 'S3_ITINERARY_READY',
    });

    useDocumentStore.getState().setFromPlanResponse(response);

    const nextDoc = useDocumentStore.getState().document!;
    expect(nextDoc.trip_inputs).toBe(tripInputs);
    expect(nextDoc.day_cards).toBe(dayCards);
    expect(nextDoc.strategy_sections).toBe(strategySections);
    expect(nextDoc.tiles).toBe(tiles);
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

describe('activity category default seeding (durability)', () => {
  // Regression: "no diving" on a built Bali plan must NOT re-seed 'cultural'.
  // The default may only seed at genuine bootstrap (no strategy_sections AND no day_cards).
  // Once a plan has content, an empty categories list is the user's deliberate removal and
  // must stay [] across the removal turn AND every subsequent unrelated turn.

  it('keeps categories empty across a removal turn AND a later unrelated turn (built plan)', () => {
    const baseTripInputs = {
      ...DEFAULT_TRIP_INPUTS,
      destination: 'Bali',
      start_date: '2026-04-01',
      end_date: '2026-04-07',
      booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' as const },
    };

    // (a) Start with a BUILT plan: strategy_sections + day_cards present, categories=['diving'].
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...baseTripInputs,
          activity_settings: { categories: ['diving'], skill_level: null, day_preferences: {} },
        },
        strategy_sections: [
          makeSection('diving', { specialist_type: 'diving' }),
          makeSection('hiking', { specialist_type: 'hiking' }),
        ],
        day_cards: [makeDayCard(1), makeDayCard(2)],
        plan_view_state: 'S3_ITINERARY_READY',
      }),
      version: 1,
    });

    // (b) Removal turn: backend prunes diving (categories=[]) and, as the staleness-clear turn,
    // ships day_cards=[]. Surviving 'hiking' section remains authoritative.
    const removalResponse = makePatchResponse(2, {
      trip_inputs: {
        ...baseTripInputs,
        activity_settings: { categories: [], skill_level: null, day_preferences: {} },
      },
      strategy_sections: [makeSection('hiking', { specialist_type: 'hiking' })],
      day_cards: [],
      tiles_replaced: true,
      plan_view_state: 'S2_STRATEGY_READY',
    });
    useDocumentStore.getState().setFromPlanResponse(removalResponse);

    const afterRemoval = useDocumentStore.getState().document!;
    // The bug would have flipped this to ['cultural']. It must stay [].
    expect(afterRemoval.trip_inputs.activity_settings?.categories).toEqual([]);

    // (c) DISCRIMINATOR: one MORE unrelated turn (categories still [], NOT a removal).
    // A naive one-turn `tiles_replaced` gate would re-default on THIS merge.
    const unrelatedResponse = makePatchResponse(3, {
      trip_inputs: {
        ...baseTripInputs,
        // An unrelated edit (e.g. adults) — categories untouched, still [].
        adults: 3,
        activity_settings: { categories: [], skill_level: null, day_preferences: {} },
      },
      strategy_sections: [makeSection('hiking', { specialist_type: 'hiking' })],
      plan_view_state: 'S2_STRATEGY_READY',
    });
    useDocumentStore.getState().setFromPlanResponse(unrelatedResponse);

    const afterUnrelated = useDocumentStore.getState().document!;
    expect(afterUnrelated.trip_inputs.activity_settings?.categories).toEqual([]);
  });

  it('keeps categories empty after a TOTAL single-specialist removal across the next turn', () => {
    // TOTAL removal: the plan had ONLY one specialist. The removal turn drops the sole
    // section AND ships day_cards=[] (backend staleness-clear), so live plan content is [].
    // The sticky session guard must latch true on the removal turn (pre-merge currentDoc
    // still had content) so the NEXT unrelated turn — with live content STILL [] — does
    // NOT re-seed 'cultural'. Step (c) FAILS without the guard (currentDoc is now empty).
    //
    // NOTE ON COMPOSITION: the clearing turn is driven through mergeEnvelope, NOT a PATCH
    // response. setFromPlanResponse short-circuits an empty strategy_sections payload to
    // currentSections (resurrection-prevention, see the 'drops a backend-removed strategy
    // section' test), so the genuine both-empty total-removal shape is only reachable via
    // mergeEnvelope, which honors an explicit [] wholesale. This mirrors the real SSE flow
    // (partials clear via mergeEnvelope, completion finalizes via setFromPlanResponse).
    const baseTripInputs = {
      ...DEFAULT_TRIP_INPUTS,
      destination: 'Bali',
      start_date: '2026-04-01',
      end_date: '2026-04-07',
      booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' as const },
    };

    // (a) Built plan with ONLY a diving section + day_cards, categories=['diving'].
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...baseTripInputs,
          activity_settings: { categories: ['diving'], skill_level: null, day_preferences: {} },
        },
        strategy_sections: [makeSection('diving', { specialist_type: 'diving' })],
        day_cards: [makeDayCard(1), makeDayCard(2)],
        plan_view_state: 'S3_ITINERARY_READY',
      }),
      version: 1,
      // Mirror a fresh session where the built plan was never observed via a merge
      // (setState bypasses the observation hooks) — the guard starts false.
      hasEverHadPlanContent: false,
    });

    // (b) TOTAL removal turn (envelope): backend drops the only section AND clears
    // day_cards. booking_types.activities stays 'suggested' (not 'off'), categories=[].
    useDocumentStore.getState().mergeEnvelope({
      trip_inputs: {
        ...baseTripInputs,
        activity_settings: { categories: [], skill_level: null, day_preferences: {} },
      },
      strategy_sections: [],
      day_cards: [],
      tiles_replaced: true,
      plan_view_state: 'S2_STRATEGY_READY',
    });

    const afterRemoval = useDocumentStore.getState().document!;
    // DISCRIMINATOR PRECONDITION: the store must reach the genuine both-empty shape.
    // If either is non-empty, step (c) would pass for the wrong reason.
    expect(afterRemoval.strategy_sections).toEqual([]);
    expect(afterRemoval.day_cards).toEqual([]);
    // The removal turn itself is safe (pre-merge currentDoc still had content).
    expect(afterRemoval.trip_inputs.activity_settings?.categories).toEqual([]);
    // Guard must have latched true from the pre-merge content.
    expect(useDocumentStore.getState().hasEverHadPlanContent).toBe(true);

    // (c) DISCRIMINATOR: one MORE unrelated turn via setFromPlanResponse (the completion
    // path). Live plan content is STILL [] (no sections, no day_cards). Without the sticky
    // guard, documentHasPlanContent of the now-empty currentDoc is false → re-seeds
    // 'cultural'. With the guard, categories stay []. Also exercises the setFromPlanResponse
    // guard read.
    const unrelatedResponse = makePatchResponse(3, {
      trip_inputs: {
        ...baseTripInputs,
        adults: 3,
        activity_settings: { categories: [], skill_level: null, day_preferences: {} },
      },
      strategy_sections: [],
      day_cards: [],
      plan_view_state: 'S2_STRATEGY_READY',
    });
    useDocumentStore.getState().setFromPlanResponse(unrelatedResponse);

    const afterUnrelated = useDocumentStore.getState().document!;
    expect(afterUnrelated.trip_inputs.activity_settings?.categories).toEqual([]);
  });

  it('keeps categories empty when an envelope removal turn clears them on a built plan', () => {
    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Bali',
          start_date: '2026-04-01',
          end_date: '2026-04-07',
          booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' },
          activity_settings: { categories: ['diving'], skill_level: null, day_preferences: {} },
        },
        strategy_sections: [makeSection('hiking', { specialist_type: 'hiking' })],
        day_cards: [makeDayCard(1)],
        plan_view_state: 'S3_ITINERARY_READY',
      }),
    });

    // Envelope (SSE partial/complete) clears categories on the same built plan.
    useDocumentStore.getState().mergeEnvelope({
      trip_inputs: {
        ...DEFAULT_TRIP_INPUTS,
        destination: 'Bali',
        start_date: '2026-04-01',
        end_date: '2026-04-07',
        booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' },
        activity_settings: { categories: [], skill_level: null, day_preferences: {} },
      },
    });

    const doc = useDocumentStore.getState().document!;
    expect(doc.trip_inputs.activity_settings?.categories).toEqual([]);
  });

  it('seeds the cultural default at bootstrap (no sections and no day_cards)', () => {
    // Brand-new trip: a bare "trip to Rome" with no stated category at S0/S1 must STILL
    // seed 'cultural' so the first activity search has something to search for.
    useDocumentStore.setState({ document: null, version: 0 });

    useDocumentStore.getState().updateTripInputs({
      destination: 'Rome',
      booking_types: { ...DEFAULT_BOOKING_TYPES, activities: 'suggested' },
      activity_settings: { categories: [], skill_level: null, day_preferences: {} },
    });

    const doc = useDocumentStore.getState().document!;
    expect(doc.strategy_sections ?? []).toHaveLength(0);
    expect(doc.day_cards ?? []).toHaveLength(0);
    expect(doc.trip_inputs.activity_settings?.categories).toEqual(['cultural']);
  });
});

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

describe('suggestion chip fields', () => {
  const chips = [
    {
      message: 'Add diving',
      action_type: 'send_message' as const,
      chip_type: 'follow_up' as const,
      category: 'activities',
    },
  ];
  const responses = ['Add diving'];
  const meta = [{ chip_type: 'follow_up' as const, category: 'activities' }];

  it('commitTripInputs carries chip fields from the PATCH response', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', budget: 3000 },
        suggestion_chips: chips,
        suggested_responses: responses,
        suggested_response_meta: meta,
      })),
    );

    const result = await useDocumentStore.getState().commitTripInputs({ budget: 3000 });

    expect(result).toBe(true);
    const doc = useDocumentStore.getState().document!;
    expect(doc.suggestion_chips).toEqual(chips);
    expect(doc.suggested_responses).toEqual(responses);
    expect(doc.suggested_response_meta).toEqual(meta);
  });

  it('commitTripInputs preserves current chip fields when the PATCH response omits them', async () => {
    useDocumentStore.setState({
      document: makeDoc({
        suggestion_chips: chips,
        suggested_responses: responses,
        suggested_response_meta: meta,
      }),
      version: 1,
    });

    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', budget: 3000 },
      })),
    );

    const result = await useDocumentStore.getState().commitTripInputs({ budget: 3000 });

    expect(result).toBe(true);
    const doc = useDocumentStore.getState().document!;
    expect(doc.suggestion_chips).toEqual(chips);
    expect(doc.suggested_responses).toEqual(responses);
    expect(doc.suggested_response_meta).toEqual(meta);
  });

  it('commitTripInputs keeps non-empty current chips over a stale PATCH echo', async () => {
    const staleChips = [
      {
        message: 'Add travel dates',
        action_type: 'open_pill' as const,
        chip_type: 'cta' as const,
        category: 'dates',
      },
    ];
    useDocumentStore.setState({
      document: makeDoc({
        suggestion_chips: chips,
        suggested_responses: responses,
        suggested_response_meta: meta,
      }),
      version: 1,
    });

    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon', budget: 3000 },
        suggestion_chips: staleChips,
        suggested_responses: ['Add travel dates'],
        suggested_response_meta: [{ chip_type: 'cta' as const, category: 'dates' }],
      })),
    );

    const result = await useDocumentStore.getState().commitTripInputs({ budget: 3000 });

    expect(result).toBe(true);
    const doc = useDocumentStore.getState().document!;
    expect(doc.suggestion_chips).toEqual(chips);
    expect(doc.suggested_responses).toEqual(responses);
    expect(doc.suggested_response_meta).toEqual(meta);
  });

  it('patchDocument carries chip fields from the PATCH response', async () => {
    useDocumentStore.setState({ document: makeDoc(), version: 1 });

    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, makePatchResponse(2, {
        suggestion_chips: chips,
        suggested_responses: responses,
        suggested_response_meta: meta,
      })),
    );

    await useDocumentStore.getState().patchDocument({ version: 1 });

    const doc = useDocumentStore.getState().document!;
    expect(doc.suggestion_chips).toEqual(chips);
    expect(doc.suggested_responses).toEqual(responses);
    expect(doc.suggested_response_meta).toEqual(meta);
  });

  it('patchDocument preserves current chip fields when the PATCH response omits them', async () => {
    useDocumentStore.setState({
      document: makeDoc({
        suggestion_chips: chips,
        suggested_responses: responses,
        suggested_response_meta: meta,
      }),
      version: 1,
    });

    mockApiFetch.mockResolvedValueOnce(mockResponse(200, makePatchResponse(2)));

    await useDocumentStore.getState().patchDocument({ version: 1 });

    const doc = useDocumentStore.getState().document!;
    expect(doc.suggestion_chips).toEqual(chips);
    expect(doc.suggested_responses).toEqual(responses);
    expect(doc.suggested_response_meta).toEqual(meta);
  });

  it('setSuggestionChipFields updates only the chip fields and bumps nothing else', () => {
    const seedDoc = makeDoc({
      day_cards: [makeDayCard(1)],
      suggested_responses: ['Old suggestion'],
    });
    useDocumentStore.setState({ document: seedDoc, version: 7 });

    useDocumentStore.getState().setSuggestionChipFields({
      suggestion_chips: chips,
      suggested_responses: responses,
      suggested_response_meta: meta,
    });

    const state = useDocumentStore.getState();
    expect(state.document!.suggestion_chips).toEqual(chips);
    expect(state.document!.suggested_responses).toEqual(responses);
    expect(state.document!.suggested_response_meta).toEqual(meta);
    // Nothing else changes: version untouched, other doc fields keep identity.
    expect(state.version).toBe(7);
    expect(state.document!.trip_inputs).toBe(seedDoc.trip_inputs);
    expect(state.document!.day_cards).toBe(seedDoc.day_cards);
    expect(state.document!.tiles).toBe(seedDoc.tiles);
  });

  it('setSuggestionChipFields treats undefined fields as no-op and empty arrays as authoritative', () => {
    useDocumentStore.setState({
      document: makeDoc({
        suggestion_chips: chips,
        suggested_responses: responses,
        suggested_response_meta: meta,
      }),
      version: 3,
    });
    const before = useDocumentStore.getState().document!;

    // All-undefined input → document untouched (referential no-op).
    useDocumentStore.getState().setSuggestionChipFields({});
    expect(useDocumentStore.getState().document).toBe(before);

    // Empty arrays are authoritative; undefined meta leaves it untouched.
    useDocumentStore.getState().setSuggestionChipFields({
      suggestion_chips: [],
      suggested_responses: [],
    });
    const after = useDocumentStore.getState().document!;
    expect(after.suggestion_chips).toEqual([]);
    expect(after.suggested_responses).toEqual([]);
    expect(after.suggested_response_meta).toEqual(meta);
  });

  it('setSuggestionChipFields is a no-op when document is null', () => {
    useDocumentStore.setState({ document: null, version: 0 });

    useDocumentStore.getState().setSuggestionChipFields({ suggestion_chips: chips });

    expect(useDocumentStore.getState().document).toBeNull();
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
