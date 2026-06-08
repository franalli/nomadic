/**
 * documentStore — Destination Lock content-preservation tests
 *
 * Regression guard for the "torn state" bug: when an incoming response/envelope
 * carries a destination different from the current one, the DESTINATION LOCK
 * forces the label back to the current value. Previously the lock preserved only
 * the label while still merging in the foreign destination's tiles / day_cards /
 * strategy_sections, corrupting the locked plan (e.g. Bali plan silently
 * regenerated for "Canggu", dropping the diving specialist + dive tiles).
 *
 * These tests assert that when the lock fires, plan CONTENT is preserved
 * wholesale, and that SAME-destination updates still merge normally (no
 * over-blocking).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { PlanDocumentData, PlanDocumentResponse } from '@/types/document';
import type { DayCard, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));
vi.mock('@/state/chatStore', () => ({
  useChatStore: { getState: () => ({ resetChat: vi.fn() }) },
}));

// ---------------------------------------------------------------------------
// Fixture factories (clean https image URLs so sanitizeDocumentImages preserves
// referential identity, letting us assert toBe on unchanged nested objects).
// ---------------------------------------------------------------------------

function makeTile(id: string, overrides: Partial<Tile> = {}): Tile {
  return {
    id,
    type: 'activity',
    title: `Tile ${id}`,
    currency: 'USD',
    deeplink_url: `https://example.com/${id}`,
    ...overrides,
  };
}

function makeSection(specialistType: string, overrides: Partial<StrategySection> = {}): StrategySection {
  return {
    id: `section_${specialistType}`,
    title: `Section ${specialistType}`,
    specialist_type: specialistType,
    principles: [],
    must_dos: [],
    optional_upgrades: [],
    logistics_notes: [],
    bullets: [],
    ...overrides,
  } as StrategySection;
}

function makeDayCard(dayNumber: number): DayCard {
  return {
    day_number: dayNumber,
    label: `Day ${dayNumber}`,
    blocks: [],
  } as DayCard;
}

// Current built "Bali" plan: 2 sections (incl. specialist_diving), 3 day_cards,
// 4 tiles (2 dive activities + 1 hotel + 1 flight).
function makeBaliDoc(): PlanDocumentData {
  return {
    trip_inputs: {
      ...DEFAULT_TRIP_INPUTS,
      destination: 'Bali',
      start_date: '2026-09-01',
      end_date: '2026-09-30',
    },
    branches: [{ id: 'b1', label: 'Bali', description: '', is_primary: true, tiles: { stays: [], flights: [], activities: [] }, selections: { activities: [] } }],
    tiles: {
      dive_1: makeTile('dive_1', { type: 'activity', title: 'Tulamben Dive' }),
      dive_2: makeTile('dive_2', { type: 'activity', title: 'USAT Liberty Wreck' }),
      hotel_1: makeTile('hotel_1', { type: 'hotel', title: 'Bali Resort' }),
      flight_1: makeTile('flight_1', { type: 'flight', title: 'DPS Flight' }),
    },
    strategy_sections: [
      makeSection('diving', { id: 'specialist_diving' }),
      makeSection('cultural', { id: 'specialist_cultural' }),
    ],
    day_cards: [makeDayCard(1), makeDayCard(2), makeDayCard(3)],
    plan_view_state: 'S3_ITINERARY_READY',
  };
}

// Foreign "Canggu" payload: rebuilt 30-day itinerary, diving section dropped.
function makeCangguContent(): Pick<PlanDocumentData, 'tiles' | 'strategy_sections' | 'day_cards'> {
  return {
    tiles: {
      surf_1: makeTile('surf_1', { type: 'activity', title: 'Canggu Surf Lesson' }),
      cafe_1: makeTile('cafe_1', { type: 'activity', title: 'Canggu Cafe Crawl' }),
    },
    strategy_sections: [makeSection('surfing', { id: 'specialist_surfing' })],
    day_cards: Array.from({ length: 30 }, (_, i) => makeDayCard(i + 1)),
  };
}

// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
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
    isRegenerating: false,
    llmUpdatedFields: new Set(),
    preferredTileIds: new Set(),
    _lastPatchedTripInputs: null,
    hasEverHadPlanContent: false,
  });
  vi.clearAllMocks();
});

describe('destination lock — setFromPlanResponse content preservation', () => {
  it('preserves Bali plan content when a foreign (Canggu) response arrives', () => {
    const baliDoc = makeBaliDoc();
    useDocumentStore.setState({ document: baliDoc });

    // Capture original references for identity assertions.
    const originalTiles = baliDoc.tiles;
    const originalSections = baliDoc.strategy_sections!;
    const originalDayCards = baliDoc.day_cards!;

    const canggu = makeCangguContent();
    const response: PlanDocumentResponse = {
      version: 5,
      updated_by: 'planner',
      updated_at: new Date().toISOString(),
      document: {
        ...makeBaliDoc(),
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Canggu',
          // Foreign dates DIFFER → the datesChanged branch would normally wipe/
          // replace content and flip isRegenerating. The lock must beat it.
          start_date: '2026-09-01',
          end_date: '2026-10-20',
        },
        tiles: canggu.tiles,
        strategy_sections: canggu.strategy_sections,
        day_cards: canggu.day_cards,
        plan_view_state: 'S2_STRATEGY_READY',
      },
    };

    useDocumentStore.getState().setFromPlanResponse(response);

    const doc = useDocumentStore.getState().document!;

    // Label preserved.
    expect(doc.trip_inputs.destination).toBe('Bali');

    // Dates preserved too — the foreign date range is rejected with the rest of
    // the foreign payload, so dates stay consistent with the preserved content.
    expect(doc.trip_inputs.start_date).toBe('2026-09-01');
    expect(doc.trip_inputs.end_date).toBe('2026-09-30');

    // Tiles UNCHANGED — same count, same ids, no Canggu tiles.
    expect(Object.keys(doc.tiles).sort()).toEqual(['dive_1', 'dive_2', 'flight_1', 'hotel_1']);
    expect(doc.tiles.surf_1).toBeUndefined();
    expect(doc.tiles).toBe(originalTiles);

    // Strategy sections UNCHANGED — diving still present, surfing absent.
    expect(doc.strategy_sections).toHaveLength(2);
    expect(doc.strategy_sections!.map((s) => s.id).sort()).toEqual([
      'specialist_cultural',
      'specialist_diving',
    ]);
    expect(doc.strategy_sections).toBe(originalSections);

    // Day cards UNCHANGED — still 3, not the foreign 30.
    expect(doc.day_cards).toHaveLength(3);
    expect(doc.day_cards).toBe(originalDayCards);

    // View state not downgraded by the foreign payload.
    expect(doc.plan_view_state).toBe('S3_ITINERARY_READY');

    // Branches preserved — the foreign destination's branches must not leak in
    // through the ...response.document base spread.
    expect(doc.branches).toBe(baliDoc.branches);

    // No spurious "dates changed" echo: the foreign dates were rejected, so the
    // planner-change highlight set must stay empty.
    expect(useDocumentStore.getState().llmUpdatedFields.size).toBe(0);
  });
});

describe('destination lock — mergeEnvelope content preservation', () => {
  it('preserves Bali plan content when a foreign (Canggu) envelope arrives', () => {
    const baliDoc = makeBaliDoc();
    useDocumentStore.setState({ document: baliDoc });

    const originalTiles = baliDoc.tiles;
    const originalSections = baliDoc.strategy_sections!;
    const originalDayCards = baliDoc.day_cards!;

    const canggu = makeCangguContent();

    useDocumentStore.getState().mergeEnvelope(
      {
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Canggu',
          // Foreign dates DIFFER → datesChanged would normally clear day_cards and
          // set isRegenerating=true. The lock must beat it.
          start_date: '2026-09-01',
          end_date: '2026-10-20',
        },
        tiles: canggu.tiles,
        strategy_sections: canggu.strategy_sections,
        day_cards: canggu.day_cards,
        plan_view_state: 'S2_STRATEGY_READY',
      },
      undefined
    );

    const doc = useDocumentStore.getState().document!;

    // Label preserved.
    expect(doc.trip_inputs.destination).toBe('Bali');

    // Dates preserved too — foreign date range rejected with the foreign payload.
    expect(doc.trip_inputs.start_date).toBe('2026-09-01');
    expect(doc.trip_inputs.end_date).toBe('2026-09-30');

    // Tiles UNCHANGED.
    expect(Object.keys(doc.tiles).sort()).toEqual(['dive_1', 'dive_2', 'flight_1', 'hotel_1']);
    expect(doc.tiles.surf_1).toBeUndefined();
    expect(doc.tiles).toBe(originalTiles);

    // Strategy sections UNCHANGED — diving still present.
    expect(doc.strategy_sections).toHaveLength(2);
    expect(doc.strategy_sections!.map((s) => s.id).sort()).toEqual([
      'specialist_cultural',
      'specialist_diving',
    ]);
    expect(doc.strategy_sections).toBe(originalSections);

    // Day cards UNCHANGED.
    expect(doc.day_cards).toHaveLength(3);
    expect(doc.day_cards).toBe(originalDayCards);

    // View state not downgraded.
    expect(doc.plan_view_state).toBe('S3_ITINERARY_READY');

    // Regen overlay not flashed.
    expect(useDocumentStore.getState().isRegenerating).toBe(false);
  });
});

describe('destination lock — regression guard (no over-blocking)', () => {
  it('setFromPlanResponse still merges same-destination content normally', () => {
    const baliDoc = makeBaliDoc();
    useDocumentStore.setState({ document: baliDoc });

    const response: PlanDocumentResponse = {
      version: 6,
      updated_by: 'planner',
      updated_at: new Date().toISOString(),
      document: {
        ...makeBaliDoc(),
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Bali',
          start_date: '2026-09-01',
          end_date: '2026-09-30',
        },
        // Same destination → a new hotel tile should merge in additively.
        tiles: {
          hotel_2: makeTile('hotel_2', { type: 'hotel', title: 'Second Bali Hotel' }),
        },
        strategy_sections: [
          makeSection('diving', { id: 'specialist_diving' }),
          makeSection('cultural', { id: 'specialist_cultural' }),
        ],
        day_cards: [makeDayCard(1), makeDayCard(2), makeDayCard(3)],
        plan_view_state: 'S3_ITINERARY_READY',
      },
    };

    useDocumentStore.getState().setFromPlanResponse(response);

    const doc = useDocumentStore.getState().document!;
    expect(doc.trip_inputs.destination).toBe('Bali');
    // New hotel merged in alongside existing tiles (additive, same destination).
    expect(doc.tiles.hotel_2).toBeDefined();
    expect(Object.keys(doc.tiles).sort()).toEqual([
      'dive_1',
      'dive_2',
      'flight_1',
      'hotel_1',
      'hotel_2',
    ]);
  });

  it('mergeEnvelope still merges same-destination content normally', () => {
    const baliDoc = makeBaliDoc();
    useDocumentStore.setState({ document: baliDoc });

    useDocumentStore.getState().mergeEnvelope(
      {
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Bali',
        },
        tiles: {
          hotel_2: makeTile('hotel_2', { type: 'hotel', title: 'Second Bali Hotel' }),
        },
      },
      undefined
    );

    const doc = useDocumentStore.getState().document!;
    expect(doc.trip_inputs.destination).toBe('Bali');
    expect(doc.tiles.hotel_2).toBeDefined();
    expect(Object.keys(doc.tiles).sort()).toEqual([
      'dive_1',
      'dive_2',
      'flight_1',
      'hotel_1',
      'hotel_2',
    ]);
  });
});
