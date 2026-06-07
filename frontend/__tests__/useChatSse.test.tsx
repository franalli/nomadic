import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockState = vi.hoisted(() => ({
  streamGraphPlan: vi.fn(),
  toast: vi.fn(),
  classifyNodeAction: vi.fn(),
  shouldShowLoaderForNode: vi.fn(),
  requestScrollTo: vi.fn(),
}));

vi.mock('@/lib/api-streaming', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-streaming')>();
  return {
    ...actual,
    streamGraphPlan: mockState.streamGraphPlan,
  };
});

vi.mock('@/components/ui/toast', () => ({
  useToast: () => ({ toast: mockState.toast }),
}));

vi.mock('@/hooks/useMapSync', () => ({
  useMapSync: {
    getState: () => ({ requestScrollTo: mockState.requestScrollTo }),
  },
}));

vi.mock('@/lib/loaderConfig', () => ({
  classifyNodeAction: mockState.classifyNodeAction,
  shouldShowLoaderForNode: mockState.shouldShowLoaderForNode,
}));

vi.mock('@/lib/debug', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/debug')>();
  return {
    ...actual,
    debugLog: vi.fn(),
    explicitDebugLog: vi.fn(),
  };
});

import type { ChatSseCallbacks, ChatSseRefs, ExecuteStreamParams } from '@/hooks/useChatSse';
import { useChatSse } from '@/hooks/useChatSse';
import { useChatStore } from '@/state/chatStore';
import {
  DEFAULT_TRIP_INPUTS,
  nextEnvelopeBufferGeneration,
  useDocumentStore,
} from '@/state/documentStore';
import type { DayCard, PlanViewState, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

function makeSection(
  id: string,
  overrides: Partial<StrategySection> = {}
): StrategySection {
  return {
    id,
    title: `Section ${id}`,
    specialist_type: 'diving',
    principles: [],
    must_dos: [],
    optional_upgrades: [],
    logistics_notes: [],
    bullets: [],
    ...overrides,
  };
}

function makeDayCard(dayNumber: number, overrides: Partial<DayCard> = {}): DayCard {
  return {
    day_number: dayNumber,
    label: `Day ${dayNumber}`,
    blocks: [],
    ...overrides,
  };
}

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

type SeedDocumentOptions = {
  strategySections?: StrategySection[];
  dayCards?: DayCard[];
  tiles?: Record<string, Tile>;
  planViewState?: PlanViewState;
};

function seedDocument(options: StrategySection[] | SeedDocumentOptions = []): void {
  const normalizedOptions = Array.isArray(options)
    ? { strategySections: options }
    : options;
  const {
    strategySections = [],
    dayCards,
    tiles = {},
    planViewState = 'S2_STRATEGY_READY',
  } = normalizedOptions;

  useDocumentStore.setState({
    document: {
      trip_context_id: null,
      trip_inputs: {
        ...DEFAULT_TRIP_INPUTS,
        destination: 'Bali',
        start_date: '2026-04-01',
        end_date: '2026-04-07',
        trip_duration: 7,
      },
      branches: [],
      tiles,
      strategy_sections: strategySections,
      ...(dayCards !== undefined && { day_cards: dayCards }),
      plan_view_state: planViewState,
    },
  });
}

function createCallbacks(): ChatSseCallbacks {
  return {
    setHasReceivedFirstToken: vi.fn(),
    setNodeStatus: vi.fn(),
    setStreamingMessageId: vi.fn(),
    setTriggerContext: vi.fn(),
    setSuggestedResponses: vi.fn(),
    setSuggestedResponseMeta: vi.fn(),
    setSuggestionChips: vi.fn(),
    setIsLoading: vi.fn(),
    setSessionState: vi.fn(),
    appendToMessage: vi.fn(),
    updateMessage: vi.fn(),
    updateMessageId: vi.fn(),
    filterMessages: vi.fn(),
    onPlanResult: vi.fn(),
    onAutoExpandItinerary: vi.fn(),
    onFeasibilityWarning: vi.fn(),
    scrollToBottom: vi.fn(),
    scrollPanelIntoView: vi.fn(),
  };
}

function createRefs(requestId: string): ChatSseRefs {
  return {
    abortStreamRef: { current: null },
    isSendingRef: { current: true },
    activeStreamRequestIdRef: { current: requestId },
    autoExpandTimeoutRef: { current: null },
    prevSpecialistTypesRef: { current: new Set() },
    prevTileTypesRef: { current: new Set() },
    prevTripInputsRef: { current: null },
  };
}

function createLoaders() {
  return {
    delayedLoader: {
      isVisible: false,
      startLoading: vi.fn(),
      onTangibleOutput: vi.fn(),
      reset: vi.fn(),
    },
    actionLoader: {
      isVisible: false,
      loaderState: null,
      title: '',
      subtext: '',
      startLoading: vi.fn(),
      onTangibleOutput: vi.fn(),
      reset: vi.fn(),
    },
  };
}

function renderUseChatSse() {
  const requestId = 'req-1';
  const refs = createRefs(requestId);
  const callbacks = createCallbacks();
  const loaders = createLoaders();

  const { result } = renderHook(() => useChatSse(refs, callbacks));
  const params: ExecuteStreamParams = {
    body: { message: 'Build my itinerary' },
    requestId,
    streamingMsgId: 'stream-msg',
    isSilentPlanGeneration: false,
    selectedBranchId: null,
    envelopeGeneration: nextEnvelopeBufferGeneration(),
    triggerContext: null,
    delayedLoader: loaders.delayedLoader as ExecuteStreamParams['delayedLoader'],
    actionLoader: loaders.actionLoader as ExecuteStreamParams['actionLoader'],
  };

  return { result, refs, callbacks, ...loaders, params };
}

describe('useChatSse', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'requestAnimationFrame',
      ((cb: FrameRequestCallback) =>
        window.setTimeout(() => cb(performance.now()), 0)) as typeof requestAnimationFrame
    );
    vi.stubGlobal(
      'cancelAnimationFrame',
      ((id: number) => window.clearTimeout(id)) as typeof cancelAnimationFrame
    );

    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    useDocumentStore.getState().reset();
    useChatStore.getState().resetChat();
    vi.clearAllMocks();

    mockState.streamGraphPlan.mockImplementation((_body, streamCallbacks) => {
      return () => {
        void streamCallbacks;
      };
    });
    mockState.classifyNodeAction.mockReturnValue({
      actionType: 'generate_plan',
      verticalType: 'activities',
    });
    mockState.shouldShowLoaderForNode.mockReturnValue(true);
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });

  it('keeps loader state active until the last overlapping node completes', async () => {
    seedDocument();
    const { result, callbacks, delayedLoader, actionLoader, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onNodeStatus?.({
        status: 'started',
        node: 'get_specialist_advice',
        label: 'Specialist',
        icon_key: 'sparkles',
        estimated_duration_ms: 1200,
      });
      streamCallbacks.onNodeStatus?.({
        status: 'started',
        node: 'search_tiles',
        label: 'Tile search',
        icon_key: 'map',
        estimated_duration_ms: 1200,
      });
      streamCallbacks.onNodeStatus?.({
        status: 'completed',
        node: 'get_specialist_advice',
        label: 'Specialist',
        icon_key: 'sparkles',
        estimated_duration_ms: 1200,
      });
    });

    expect(callbacks.setNodeStatus).toHaveBeenLastCalledWith(
      expect.objectContaining({ node: 'search_tiles', active: true })
    );
    expect(delayedLoader.startLoading).toHaveBeenCalledTimes(2);
    expect(actionLoader.startLoading).toHaveBeenCalledTimes(2);
    expect(delayedLoader.reset).not.toHaveBeenCalled();
    expect(actionLoader.reset).not.toHaveBeenCalled();

    act(() => {
      streamCallbacks.onNodeStatus?.({
        status: 'completed',
        node: 'search_tiles',
        label: 'Tile search',
        icon_key: 'map',
        estimated_duration_ms: 1200,
      });
    });

    expect(callbacks.setNodeStatus).toHaveBeenLastCalledWith(null);
    expect(delayedLoader.reset).toHaveBeenCalledTimes(1);
    expect(actionLoader.reset).toHaveBeenCalledTimes(1);

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('applies specialist preview immediately and defers the compatibility strategy merge', async () => {
    const staleSection = makeSection('stale', {
      title: 'Old Hiking Plan',
      specialist_type: 'hiking',
    });
    const authoritativeSection = makeSection('final', {
      title: 'Dive Plan',
      specialist_type: 'diving',
    });

    seedDocument([staleSection]);
    const { result, params } = renderUseChatSse();
    const mergeEnvelopeSpy = vi.spyOn(useDocumentStore.getState(), 'mergeEnvelope');

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'specialist_preview',
        payload: {
          topics: ['diving'],
          activities: [
            {
              title: 'USAT Liberty Shipwreck Shore Dive',
              specialist_type: 'diving',
              duration_hours: 3,
              description: 'Easy-entry wreck dive with strong marine life.',
            },
          ],
          strategy_sections: [authoritativeSection],
        },
      });
      streamCallbacks.onPartial?.({
        kind: 'strategy_sections',
        payload: [authoritativeSection],
      });
    });

    expect(useDocumentStore.getState().document?.strategy_sections).toEqual([
      authoritativeSection,
    ]);
    expect(useDocumentStore.getState()._specialistPreview).toEqual([
      {
        title: 'USAT Liberty Shipwreck Shore Dive',
        specialist_type: 'diving',
        duration_hours: 3,
        description: 'Easy-entry wreck dive with strong marine life.',
      },
    ]);
    expect(mergeEnvelopeSpy).not.toHaveBeenCalled();

    await act(async () => {
      vi.runAllTimers();
    });

    expect(mergeEnvelopeSpy).toHaveBeenCalledWith(
      { strategy_sections: [authoritativeSection] },
      params.envelopeGeneration
    );

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
    mergeEnvelopeSpy.mockRestore();
  });

  it('clears specialist preview state when the stream errors before complete', async () => {
    seedDocument();
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'specialist_preview',
        payload: {
          topics: ['diving'],
          activities: [
            {
              title: 'USAT Liberty Shipwreck Shore Dive',
              specialist_type: 'diving',
              duration_hours: 3,
            },
          ],
        },
      });
    });

    expect(useDocumentStore.getState()._specialistPreview).toEqual([
      {
        title: 'USAT Liberty Shipwreck Shore Dive',
        specialist_type: 'diving',
        duration_hours: 3,
      },
    ]);

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    expect(useDocumentStore.getState()._specialistPreview).toBeNull();
    await expect(streamResult).resolves.toBe('error');
  });

  it('keeps the newest strategy sections when a later payload arrives before the deferred merge flushes', async () => {
    const previewSection = makeSection('preview', {
      title: 'Preview Dive Plan',
      specialist_type: 'diving',
    });
    const localIntelSection = makeSection('local-intel', {
      title: 'Local Intel Update',
      specialist_type: 'local_expert',
    });

    seedDocument();
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'specialist_preview',
        payload: {
          topics: ['diving'],
          activities: [
            {
              title: 'Preview Dive Plan',
              specialist_type: 'diving',
              duration_hours: 3,
            },
          ],
          strategy_sections: [previewSection],
        },
      });
      streamCallbacks.onPartial?.({
        kind: 'strategy_sections',
        payload: [previewSection],
      });
      streamCallbacks.onPartial?.({
        kind: 'strategy_sections',
        payload: [localIntelSection],
      });
    });

    expect(useDocumentStore.getState().document?.strategy_sections).toEqual([
      localIntelSection,
    ]);

    await act(async () => {
      vi.runAllTimers();
    });

    expect(useDocumentStore.getState().document?.strategy_sections).toEqual([
      localIntelSection,
    ]);

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('preserves the latest strategy sections when the document store RAF buffer is enabled', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    vi.stubEnv('VITEST', 'false');

    const previewSection = makeSection('preview', {
      title: 'Preview Dive Plan',
      specialist_type: 'diving',
    });
    const localIntelSection = makeSection('local-intel', {
      title: 'Local Intel Update',
      specialist_type: 'local_expert',
    });

    seedDocument();
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'specialist_preview',
        payload: {
          topics: ['diving'],
          activities: [
            {
              title: 'Preview Dive Plan',
              specialist_type: 'diving',
              duration_hours: 3,
            },
          ],
          strategy_sections: [previewSection],
        },
      });
      streamCallbacks.onPartial?.({
        kind: 'strategy_sections',
        payload: [previewSection],
      });
      streamCallbacks.onPartial?.({
        kind: 'strategy_sections',
        payload: [localIntelSection],
      });
    });

    expect(useDocumentStore.getState().document?.strategy_sections).toEqual([
      previewSection,
    ]);

    await act(async () => {
      vi.runAllTimers();
    });

    expect(useDocumentStore.getState().document?.strategy_sections).toEqual([
      localIntelSection,
    ]);

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('drops a deferred compatibility merge after the active request id changes', async () => {
    const previewSection = makeSection('preview', {
      title: 'Preview Dive Plan',
      specialist_type: 'diving',
    });

    seedDocument();
    const { result, params, refs } = renderUseChatSse();
    const mergeEnvelopeSpy = vi.spyOn(useDocumentStore.getState(), 'mergeEnvelope');

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'specialist_preview',
        payload: {
          topics: ['diving'],
          activities: [
            {
              title: 'Preview Dive Plan',
              specialist_type: 'diving',
              duration_hours: 3,
            },
          ],
          strategy_sections: [previewSection],
        },
      });
      streamCallbacks.onPartial?.({
        kind: 'strategy_sections',
        payload: [previewSection],
      });
    });

    refs.activeStreamRequestIdRef.current = 'req-2';

    await act(async () => {
      vi.runAllTimers();
    });

    expect(useDocumentStore.getState().document?.strategy_sections).toEqual([
      previewSection,
    ]);
    expect(mergeEnvelopeSpy).not.toHaveBeenCalled();

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('stale');
    mergeEnvelopeSpy.mockRestore();
  });

  it('merges day_cards partial payload context and warnings into the document store', async () => {
    const dayCards = [makeDayCard(1, { label: 'Arrival + snorkel' })];
    const itineraryOverview = {
      duration_label: '7 days',
      base_structure: 'Single base',
      activity_density: '2 activities/day',
    };
    const itineraryAssumptions = {
      assumptions: ['Boat transfer required'],
      flexible_elements: ['Swap Day 3 dive site'],
    };
    const constraintViolations = [
      {
        code: 'late_arrival',
        message: 'Arrival lands after boat departure.',
        severity: 'warning',
        category: 'timing',
      },
    ];

    seedDocument();
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'day_cards',
        payload: {
          day_cards: dayCards,
          plan_view_state: 'S3_ITINERARY_READY',
          itinerary_overview: itineraryOverview,
          itinerary_assumptions: itineraryAssumptions,
          constraint_violations: constraintViolations,
          warnings: ['Keep a no-fly buffer after the final dive day.'],
        },
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: dayCards,
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
    });
    expect(mockState.toast).toHaveBeenCalledWith(
      'Keep a no-fly buffer after the final dive day.',
      { type: 'warning', duration: 4000 }
    );

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('merges tile_enrichment day cards, tiles, and context when the payload is marked changed', async () => {
    const existingStayTile = makeTile('stay-1', { type: 'stay' });
    const enrichedActivityTile = makeTile('activity-1', { type: 'activity' });
    const enrichedDayCards = [makeDayCard(2, { label: 'Two-tank dive day' })];
    const itineraryOverview = {
      duration_label: '7 days',
      base_structure: 'Two bases',
      activity_density: '1 activity/day',
    };

    seedDocument({
      tiles: { [existingStayTile.id]: existingStayTile },
    });
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'tile_enrichment',
        payload: {
          day_cards: enrichedDayCards,
          tiles: { [enrichedActivityTile.id]: enrichedActivityTile },
          plan_view_state: 'S3_ITINERARY_READY',
          itinerary_overview: itineraryOverview,
        },
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: enrichedDayCards,
      itinerary_overview: itineraryOverview,
      tiles: {
        [existingStayTile.id]: existingStayTile,
        [enrichedActivityTile.id]: enrichedActivityTile,
      },
    });

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('replays the backend itinerary enrichment partial sequence without duplicating warning toasts', async () => {
    const staleStayTile = makeTile('stay-stale', {
      type: 'stay',
      title: 'Old Harbor Stay',
    });
    const staleActivityTile = makeTile('activity-stale', {
      type: 'activity',
      title: 'Old Reef Dive',
    });
    const refreshedStayTile = makeTile('stay-refresh', {
      type: 'stay',
      title: 'Cliffside Resort',
    });
    const refreshedActivityTile = makeTile('activity-refresh', {
      type: 'activity',
      title: 'Manta Point Drift',
    });
    const initialDayCards = [
      makeDayCard(1, { label: 'Arrival + resort transfer' }),
      makeDayCard(2, { label: 'Warm-up reef checkout dive' }),
    ];
    const enrichedDayCards = [
      makeDayCard(1, { label: 'Arrival + resort transfer' }),
      makeDayCard(2, { label: 'Manta Point double-dive' }),
    ];
    const itineraryOverview = {
      duration_label: '7 days',
      base_structure: 'Two bases',
      activity_density: '2 dives/day',
    };
    const itineraryAssumptions = {
      assumptions: ['Boat departures depend on morning sea conditions'],
      flexible_elements: ['Swap Day 2 and Day 3 based on currents'],
    };
    const constraintViolations = [
      {
        code: 'nofly_buffer',
        message: 'Keep a 24-hour no-fly buffer after your final dive.',
        severity: 'warning',
        category: 'safety',
      },
    ];
    const warningMessage = 'Keep a 24-hour no-fly buffer after your final dive.';
    const replacementTiles = {
      [refreshedStayTile.id]: refreshedStayTile,
      [refreshedActivityTile.id]: refreshedActivityTile,
    };
    const enrichmentContext = {
      plan_view_state: 'S3_ITINERARY_READY',
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      warnings: [warningMessage],
    };

    seedDocument({
      tiles: {
        [staleStayTile.id]: staleStayTile,
        [staleActivityTile.id]: staleActivityTile,
      },
    });
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'day_cards',
        payload: {
          day_cards: initialDayCards,
          ...enrichmentContext,
        },
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: initialDayCards,
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      tiles: {
        [staleStayTile.id]: staleStayTile,
        [staleActivityTile.id]: staleActivityTile,
      },
    });
    expect(mockState.toast).toHaveBeenCalledTimes(1);
    expect(mockState.toast).toHaveBeenCalledWith(warningMessage, {
      type: 'warning',
      duration: 4000,
    });

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'tile_enrichment',
        payload: {
          day_cards: enrichedDayCards,
          tiles: replacementTiles,
          day_cards_changed: true,
          tiles_changed: true,
          ...enrichmentContext,
        },
        tiles_replaced: true,
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: enrichedDayCards,
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      tiles: replacementTiles,
    });
    expect(useDocumentStore.getState().document?.tiles).toEqual(replacementTiles);
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(staleStayTile.id);
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(
      staleActivityTile.id
    );
    expect(mockState.toast).toHaveBeenCalledTimes(1);

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'day_cards',
        payload: {
          day_cards: enrichedDayCards,
          ...enrichmentContext,
        },
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: enrichedDayCards,
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      tiles: replacementTiles,
    });
    expect(mockState.toast).toHaveBeenCalledTimes(1);

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'tiles',
        payload: replacementTiles,
        tiles_replaced: true,
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: enrichedDayCards,
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      tiles: replacementTiles,
    });
    expect(useDocumentStore.getState().document?.tiles).toEqual(replacementTiles);
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(staleStayTile.id);
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(
      staleActivityTile.id
    );
    expect(mockState.toast).toHaveBeenCalledTimes(1);
    expect(mockState.toast).toHaveBeenCalledWith(warningMessage, {
      type: 'warning',
      duration: 4000,
    });

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('replays the itinerary enrichment partial sequence through the RAF buffer without duplicating warning toasts', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    vi.stubEnv('VITEST', 'false');

    const staleStayTile = makeTile('stay-stale', {
      type: 'stay',
      title: 'Old Harbor Stay',
    });
    const staleActivityTile = makeTile('activity-stale', {
      type: 'activity',
      title: 'Old Reef Dive',
    });
    const refreshedStayTile = makeTile('stay-refresh', {
      type: 'stay',
      title: 'Cliffside Resort',
    });
    const refreshedActivityTile = makeTile('activity-refresh', {
      type: 'activity',
      title: 'Manta Point Drift',
    });
    const initialDayCards = [
      makeDayCard(1, { label: 'Arrival + resort transfer' }),
      makeDayCard(2, { label: 'Warm-up reef checkout dive' }),
    ];
    const enrichedDayCards = [
      makeDayCard(1, { label: 'Arrival + resort transfer' }),
      makeDayCard(2, { label: 'Manta Point double-dive' }),
    ];
    const itineraryOverview = {
      duration_label: '7 days',
      base_structure: 'Two bases',
      activity_density: '2 dives/day',
    };
    const itineraryAssumptions = {
      assumptions: ['Boat departures depend on morning sea conditions'],
      flexible_elements: ['Swap Day 2 and Day 3 based on currents'],
    };
    const constraintViolations = [
      {
        code: 'nofly_buffer',
        message: 'Keep a 24-hour no-fly buffer after your final dive.',
        severity: 'warning',
        category: 'safety',
      },
    ];
    const warningMessage = 'Keep a 24-hour no-fly buffer after your final dive.';
    const replacementTiles = {
      [refreshedStayTile.id]: refreshedStayTile,
      [refreshedActivityTile.id]: refreshedActivityTile,
    };
    const enrichmentContext = {
      plan_view_state: 'S3_ITINERARY_READY',
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      warnings: [warningMessage],
    };

    seedDocument({
      tiles: {
        [staleStayTile.id]: staleStayTile,
        [staleActivityTile.id]: staleActivityTile,
      },
    });
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'day_cards',
        payload: {
          day_cards: initialDayCards,
          ...enrichmentContext,
        },
      });
      streamCallbacks.onPartial?.({
        kind: 'tile_enrichment',
        payload: {
          day_cards: enrichedDayCards,
          tiles: replacementTiles,
          day_cards_changed: true,
          tiles_changed: true,
          ...enrichmentContext,
        },
        tiles_replaced: true,
      });
      streamCallbacks.onPartial?.({
        kind: 'day_cards',
        payload: {
          day_cards: enrichedDayCards,
          ...enrichmentContext,
        },
      });
      streamCallbacks.onPartial?.({
        kind: 'tiles',
        payload: replacementTiles,
        tiles_replaced: true,
      });
    });

    expect(useDocumentStore.getState().document?.tiles).toEqual({
      [staleStayTile.id]: staleStayTile,
      [staleActivityTile.id]: staleActivityTile,
    });
    expect(useDocumentStore.getState().document?.day_cards).toBeUndefined();
    expect(mockState.toast).toHaveBeenCalledTimes(1);
    expect(mockState.toast).toHaveBeenCalledWith(warningMessage, {
      type: 'warning',
      duration: 4000,
    });

    await act(async () => {
      vi.runAllTimers();
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: enrichedDayCards,
      itinerary_overview: itineraryOverview,
      itinerary_assumptions: itineraryAssumptions,
      constraint_violations: constraintViolations,
      tiles: replacementTiles,
    });
    expect(useDocumentStore.getState().document?.tiles).toEqual(replacementTiles);
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(staleStayTile.id);
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(
      staleActivityTile.id
    );
    // Builder warning toast fires once; watchdog timer may also fire during
    // vi.runAllTimers() since no onComplete/onError has arrived yet.
    expect(mockState.toast).toHaveBeenCalledWith(warningMessage, {
      type: 'warning',
      duration: 4000,
    });

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('preserves existing day cards when tile_enrichment marks them unchanged', async () => {
    const existingDayCards = [makeDayCard(1, { label: 'Existing itinerary' })];
    const incomingDayCards = [makeDayCard(1, { label: 'Should not replace existing itinerary' })];
    const existingStayTile = makeTile('stay-1', { type: 'stay' });
    const enrichedActivityTile = makeTile('activity-2', { type: 'activity' });

    seedDocument({
      dayCards: existingDayCards,
      tiles: { [existingStayTile.id]: existingStayTile },
      planViewState: 'S3_ITINERARY_READY',
    });
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'tile_enrichment',
        payload: {
          day_cards: incomingDayCards,
          day_cards_changed: false,
          tiles: { [enrichedActivityTile.id]: enrichedActivityTile },
          plan_view_state: 'S3_EDITING',
        },
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_EDITING',
      day_cards: existingDayCards,
      tiles: {
        [existingStayTile.id]: existingStayTile,
        [enrichedActivityTile.id]: enrichedActivityTile,
      },
    });

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  it('preserves existing tiles when tile_enrichment marks them unchanged', async () => {
    const enrichedDayCards = [makeDayCard(3, { label: 'Updated shore dive day' })];
    const existingStayTile = makeTile('stay-1', { type: 'stay' });
    const incomingActivityTile = makeTile('activity-3', { type: 'activity' });

    seedDocument({
      tiles: { [existingStayTile.id]: existingStayTile },
    });
    const { result, params } = renderUseChatSse();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    act(() => {
      streamCallbacks.onPartial?.({
        kind: 'tile_enrichment',
        payload: {
          day_cards: enrichedDayCards,
          tiles: { [incomingActivityTile.id]: incomingActivityTile },
          tiles_changed: false,
          plan_view_state: 'S3_ITINERARY_READY',
        },
      });
    });

    expect(useDocumentStore.getState().document).toMatchObject({
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: enrichedDayCards,
      tiles: {
        [existingStayTile.id]: existingStayTile,
      },
    });
    expect(useDocumentStore.getState().document?.tiles).not.toHaveProperty(
      incomingActivityTile.id
    );

    act(() => {
      streamCallbacks.onError(new Error('stop test stream'));
      vi.runAllTimers();
    });

    await expect(streamResult).resolves.toBe('error');
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Auto-expand gate on SSE complete — natural-language specialist removal.
  //
  // A removal turn ("no diving") returns day_cards: [] on the complete
  // envelope and relies on the frontend auto-expand gate to REBUILD the
  // itinerary from the surviving (pruned) tiles. These two tests discriminate
  // on `doc.day_cards`: case 1 has `[]` (must fire the expand), case 2 has a
  // day card carrying a REAL activity block (must skip — graphBuiltItinerary
  // path). The skip path is content-aware: a day_cards set counts as "built"
  // only when it contains at least one real activity block, so case 2's card
  // must include one. If the gate failed to fire on day_cards=[], case 1 would
  // behave like case 2 and fail.
  // ─────────────────────────────────────────────────────────────────────────

  type CompleteEnvelopeOverrides = {
    dayCards: DayCard[];
    strategySections: StrategySection[];
    tiles?: Record<string, Tile>;
    planViewState?: PlanViewState;
  };

  function makeCompleteEnvelope({
    dayCards,
    strategySections,
    tiles = {},
    planViewState = 'S3_ITINERARY_READY',
  }: CompleteEnvelopeOverrides) {
    return {
      version: 1,
      updated_by: 'planner',
      updated_at: '2026-04-01T00:00:00Z',
      changes_made: true,
      request_id: 'req-1',
      session_state: {},
      document: {
        trip_context_id: null,
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Bali',
          start_date: '2026-04-01',
          end_date: '2026-04-07',
          trip_duration: 7,
        },
        branches: [],
        tiles,
        strategy_sections: strategySections,
        day_cards: dayCards,
        plan_view_state: planViewState,
        tiles_replaced: true,
      },
    };
  }

  it('schedules an auto-expand when a removal turn clears day_cards to [] on complete', async () => {
    // Surviving (non-removed) section after "no diving" — the diving section
    // is absent. Pre-turn store already has an itinerary (this is a removal,
    // not a first build).
    const survivingSection = makeSection('local-intel', {
      title: 'Local Intel',
      specialist_type: 'local_expert',
    });

    seedDocument({
      strategySections: [survivingSection],
      dayCards: [makeDayCard(1, { label: 'Existing itinerary' })],
      planViewState: 'S3_ITINERARY_READY',
    });

    const { result, callbacks, refs, params } = renderUseChatSse();

    // Mirror the real onPlanResult: apply the response document's day_cards to
    // the store (the no-op default would leave the seeded itinerary in place).
    (callbacks.onPlanResult as ReturnType<typeof vi.fn>).mockImplementation(() => {
      useDocumentStore.setState((state) => ({
        document: state.document
          ? { ...state.document, day_cards: [], strategy_sections: [survivingSection] }
          : state.document,
      }));
    });

    // Pre-removal specialist/tile state so the surviving section does NOT read
    // as a *new* specialist — the gate then resolves CATCH_ALL (not STRUCTURAL).
    refs.prevSpecialistTypesRef.current = new Set(['local_expert']);
    refs.prevTileTypesRef.current = new Set();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    await act(async () => {
      streamCallbacks.onComplete(
        makeCompleteEnvelope({
          dayCards: [],
          strategySections: [survivingSection],
          planViewState: 'S3_ITINERARY_READY',
        })
      );
    });

    await expect(streamResult).resolves.toBe('complete');

    // Auto-expand is scheduled via setTimeout(..., 100); flush it.
    expect(callbacks.onAutoExpandItinerary).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(callbacks.onAutoExpandItinerary).toHaveBeenCalledTimes(1);
    expect(callbacks.onAutoExpandItinerary).toHaveBeenCalledWith({
      forceFullRebuild: true,
    });
  });

  it('skips auto-expand when the graph response already includes day_cards', async () => {
    // Identical to the previous test except day_cards is non-empty — the
    // graphBuiltItinerary path must short-circuit the expand.
    const survivingSection = makeSection('local-intel', {
      title: 'Local Intel',
      specialist_type: 'local_expert',
    });

    seedDocument({
      strategySections: [survivingSection],
      dayCards: [makeDayCard(1, { label: 'Existing itinerary' })],
      planViewState: 'S3_ITINERARY_READY',
    });

    const { result, callbacks, refs, params } = renderUseChatSse();

    // Card carries a REAL activity block — content-aware skip requires it.
    const graphDayCards = [
      makeDayCard(1, {
        label: 'Graph-built day 1',
        blocks: [
          {
            period: 'morning',
            activity_type: 'snorkeling',
            summary: 'Reef snorkel at Blue Lagoon',
          },
        ],
      }),
    ];
    (callbacks.onPlanResult as ReturnType<typeof vi.fn>).mockImplementation(() => {
      useDocumentStore.setState((state) => ({
        document: state.document
          ? {
              ...state.document,
              day_cards: graphDayCards,
              strategy_sections: [survivingSection],
            }
          : state.document,
      }));
    });

    refs.prevSpecialistTypesRef.current = new Set(['local_expert']);
    refs.prevTileTypesRef.current = new Set();

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    await act(async () => {
      streamCallbacks.onComplete(
        makeCompleteEnvelope({
          dayCards: graphDayCards,
          strategySections: [survivingSection],
          planViewState: 'S3_ITINERARY_READY',
        })
      );
    });

    await expect(streamResult).resolves.toBe('complete');

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(callbacks.onAutoExpandItinerary).not.toHaveBeenCalled();
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Fix 2 (defense-in-depth): a graph response whose day_cards are ALL
  // Free-Day / buffer placeholders is degenerate — it is NOT a finished build,
  // so the gate must fall through to a corrective expand (DEGENERATE_REBUILD)
  // when activities are enabled AND at least one activity tile exists to place.
  // The companion test above ("skip auto-expand when the graph response already
  // includes day_cards") proves the inverse: a card with a real activity block
  // does NOT trigger the corrective expand.
  // ─────────────────────────────────────────────────────────────────────────

  it('falls through to a corrective expand when graph day_cards are all Free-Day/buffer placeholders', async () => {
    const survivingSection = makeSection('local-intel', {
      title: 'Local Intel',
      specialist_type: 'local_expert',
    });
    const activityTile = makeTile('exp_bali_outdoor_0', { type: 'activity' });
    // Degenerate day_cards: only Free-Day + buffer blocks, no real activity.
    const degenerateDayCards = [
      makeDayCard(1, {
        label: 'Free day',
        blocks: [{ period: 'morning', activity_type: 'free_day', summary: 'Open day' }],
      }),
      makeDayCard(2, {
        label: 'No-fly buffer',
        blocks: [
          {
            period: 'morning',
            activity_type: 'buffer',
            summary: '24h surface interval',
            is_buffer: true,
            buffer_type: 'no_fly',
          },
        ],
      }),
    ];

    seedDocument({
      strategySections: [survivingSection],
      dayCards: degenerateDayCards,
      tiles: { [activityTile.id]: activityTile },
      planViewState: 'S3_ITINERARY_READY',
    });
    // Explicit activities-on so the regression-b guard (activities !== 'off')
    // is satisfied deterministically rather than via DEFAULT_TRIP_INPUTS.
    useDocumentStore.setState((state) => ({
      document: state.document
        ? {
            ...state.document,
            trip_inputs: {
              ...state.document.trip_inputs,
              booking_types: {
                ...state.document.trip_inputs.booking_types!,
                activities: 'on',
              },
            },
          }
        : state.document,
    }));

    const { result, callbacks, refs, params } = renderUseChatSse();

    (callbacks.onPlanResult as ReturnType<typeof vi.fn>).mockImplementation(() => {
      useDocumentStore.setState((state) => ({
        document: state.document
          ? {
              ...state.document,
              day_cards: degenerateDayCards,
              strategy_sections: [survivingSection],
            }
          : state.document,
      }));
    });

    // Neutralize STRUCTURAL: activity tile category is already "seen", so the
    // degenerate reason is the ONLY possible trigger.
    refs.prevSpecialistTypesRef.current = new Set(['local_expert']);
    refs.prevTileTypesRef.current = new Set(['activity']);

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    await act(async () => {
      streamCallbacks.onComplete(
        makeCompleteEnvelope({
          dayCards: degenerateDayCards,
          strategySections: [survivingSection],
          tiles: { [activityTile.id]: activityTile },
          planViewState: 'S3_ITINERARY_READY',
        })
      );
    });

    await expect(streamResult).resolves.toBe('complete');

    expect(callbacks.onAutoExpandItinerary).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(callbacks.onAutoExpandItinerary).toHaveBeenCalledTimes(1);
    expect(callbacks.onAutoExpandItinerary).toHaveBeenCalledWith({
      forceFullRebuild: true,
    });
  });

  it('treats logistics-anchor-only day_cards (arrival/free_day, no activity) as degenerate and rebuilds', async () => {
    // Anchors (arrival/departure/check-in/check-out) arrive as activity_type,
    // not as buffers — a plan that is ONLY anchors + free days is degenerate
    // and must still trigger the corrective expand.
    const survivingSection = makeSection('local-intel', {
      title: 'Local Intel',
      specialist_type: 'local_expert',
    });
    const activityTile = makeTile('exp_bali_outdoor_0', { type: 'activity' });
    const degenerateDayCards = [
      makeDayCard(1, {
        label: 'Arrival',
        blocks: [{ period: 'morning', activity_type: 'arrival', summary: 'Land at DPS' }],
      }),
      makeDayCard(2, {
        label: 'Free day',
        blocks: [{ period: 'morning', activity_type: 'free_day', summary: 'Open day' }],
      }),
    ];

    seedDocument({
      strategySections: [survivingSection],
      dayCards: degenerateDayCards,
      tiles: { [activityTile.id]: activityTile },
      planViewState: 'S3_ITINERARY_READY',
    });
    useDocumentStore.setState((state) => ({
      document: state.document
        ? {
            ...state.document,
            trip_inputs: {
              ...state.document.trip_inputs,
              booking_types: {
                ...state.document.trip_inputs.booking_types!,
                activities: 'on',
              },
            },
          }
        : state.document,
    }));

    const { result, callbacks, refs, params } = renderUseChatSse();

    (callbacks.onPlanResult as ReturnType<typeof vi.fn>).mockImplementation(() => {
      useDocumentStore.setState((state) => ({
        document: state.document
          ? {
              ...state.document,
              day_cards: degenerateDayCards,
              strategy_sections: [survivingSection],
            }
          : state.document,
      }));
    });

    refs.prevSpecialistTypesRef.current = new Set(['local_expert']);
    refs.prevTileTypesRef.current = new Set(['activity']);

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    await act(async () => {
      streamCallbacks.onComplete(
        makeCompleteEnvelope({
          dayCards: degenerateDayCards,
          strategySections: [survivingSection],
          tiles: { [activityTile.id]: activityTile },
          planViewState: 'S3_ITINERARY_READY',
        })
      );
    });

    await expect(streamResult).resolves.toBe('complete');

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(callbacks.onAutoExpandItinerary).toHaveBeenCalledTimes(1);
    expect(callbacks.onAutoExpandItinerary).toHaveBeenCalledWith({
      forceFullRebuild: true,
    });
  });

  it('does NOT correct degenerate day_cards when there is no activity tile to place', async () => {
    const survivingSection = makeSection('local-intel', {
      title: 'Local Intel',
      specialist_type: 'local_expert',
    });
    const stayTile = makeTile('stay-1', { type: 'stay' });
    const degenerateDayCards = [
      makeDayCard(1, {
        label: 'Free day',
        blocks: [{ period: 'morning', activity_type: 'free_day', summary: 'Open day' }],
      }),
    ];

    seedDocument({
      strategySections: [survivingSection],
      dayCards: degenerateDayCards,
      tiles: { [stayTile.id]: stayTile },
      planViewState: 'S3_ITINERARY_READY',
    });

    const { result, callbacks, refs, params } = renderUseChatSse();

    (callbacks.onPlanResult as ReturnType<typeof vi.fn>).mockImplementation(() => {
      useDocumentStore.setState((state) => ({
        document: state.document
          ? {
              ...state.document,
              day_cards: degenerateDayCards,
              strategy_sections: [survivingSection],
            }
          : state.document,
      }));
    });

    // No new specialist/tile categories → STRUCTURAL is neutralized too, so the
    // only candidate would be DEGENERATE — which must be blocked by the missing
    // activity tile.
    refs.prevSpecialistTypesRef.current = new Set(['local_expert']);
    refs.prevTileTypesRef.current = new Set(['stay']);

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    await act(async () => {
      streamCallbacks.onComplete(
        makeCompleteEnvelope({
          dayCards: degenerateDayCards,
          strategySections: [survivingSection],
          tiles: { [stayTile.id]: stayTile },
          planViewState: 'S3_ITINERARY_READY',
        })
      );
    });

    await expect(streamResult).resolves.toBe('complete');

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(callbacks.onAutoExpandItinerary).not.toHaveBeenCalled();
  });

  it('does NOT correct degenerate day_cards for a legitimately activity-free trip (activities off)', async () => {
    // Regression-(b) guard: a trip with booking_types.activities === 'off' is
    // INTENTIONALLY activity-free. An all-Free-Day plan is correct there and must
    // NOT trigger a corrective expand — even though an activity tile exists (which
    // distinguishes this from the missing-tile case above; here only the
    // activities-off guard blocks the rebuild).
    const survivingSection = makeSection('local-intel', {
      title: 'Local Intel',
      specialist_type: 'local_expert',
    });
    const activityTile = makeTile('exp_bali_outdoor_0', { type: 'activity' });
    const degenerateDayCards = [
      makeDayCard(1, {
        label: 'Free day',
        blocks: [{ period: 'morning', activity_type: 'free_day', summary: 'Open day' }],
      }),
    ];

    seedDocument({
      strategySections: [survivingSection],
      dayCards: degenerateDayCards,
      tiles: { [activityTile.id]: activityTile },
      planViewState: 'S3_ITINERARY_READY',
    });
    // Activities explicitly OFF — the only thing that should block the rebuild.
    useDocumentStore.setState((state) => ({
      document: state.document
        ? {
            ...state.document,
            trip_inputs: {
              ...state.document.trip_inputs,
              booking_types: {
                ...state.document.trip_inputs.booking_types!,
                activities: 'off',
              },
            },
          }
        : state.document,
    }));

    const { result, callbacks, refs, params } = renderUseChatSse();

    (callbacks.onPlanResult as ReturnType<typeof vi.fn>).mockImplementation(() => {
      useDocumentStore.setState((state) => ({
        document: state.document
          ? {
              ...state.document,
              day_cards: degenerateDayCards,
              strategy_sections: [survivingSection],
            }
          : state.document,
      }));
    });

    // Neutralize STRUCTURAL so DEGENERATE would be the only candidate — and prove
    // the activities-off guard is what blocks it.
    refs.prevSpecialistTypesRef.current = new Set(['local_expert']);
    refs.prevTileTypesRef.current = new Set(['activity']);

    let streamResult!: Promise<'complete' | 'error' | 'stale'>;
    await act(async () => {
      streamResult = result.current.executeStream(params);
    });

    const streamCallbacks = mockState.streamGraphPlan.mock.calls[0][1];

    await act(async () => {
      streamCallbacks.onComplete(
        makeCompleteEnvelope({
          dayCards: degenerateDayCards,
          strategySections: [survivingSection],
          tiles: { [activityTile.id]: activityTile },
          planViewState: 'S3_ITINERARY_READY',
        })
      );
    });

    await expect(streamResult).resolves.toBe('complete');

    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(callbacks.onAutoExpandItinerary).not.toHaveBeenCalled();
  });
});
