import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/streamParser', () => ({
  consumeNdjsonEnvelopeStream: vi.fn(async (_body, callbacks: Record<string, unknown>) => {
    const onDone = callbacks.onDone as
      | ((event: { type: 'done'; plan_view_state: 'S3_ITINERARY_READY'; version: number }) => void)
      | undefined;
    onDone?.({ type: 'done', plan_view_state: 'S3_ITINERARY_READY', version: 2 });
  }),
}));

import { useItineraryGeneration } from '@/components/layout/hooks/useItineraryGeneration';
import { apiFetch } from '@/lib/api';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

const mockApiFetch = vi.mocked(apiFetch);

const BASE_SECTION: StrategySection = {
  id: 'hiking',
  title: 'Hiking',
  specialist_type: 'hiking',
  principles: [],
  must_dos: [],
  optional_upgrades: [],
  logistics_notes: [],
  bullets: [],
};

describe('useItineraryGeneration dedupe', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useDocumentStore.getState().reset();
    useDocumentStore.setState({
      version: 1,
      currentRunId: null,
      expandInProgress: false,
      isRegenerating: false,
      document: {
        trip_context_id: null,
        trip_inputs: {
          ...DEFAULT_TRIP_INPUTS,
          destination: 'Rome',
          start_date: '2026-03-01',
          end_date: '2026-03-07',
        },
        branches: [],
        tiles: {},
        strategy_sections: [BASE_SECTION],
        plan_view_state: 'S2_STRATEGY_READY',
        day_cards: [],
      },
    });
    mockApiFetch.mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      body: new ReadableStream<Uint8Array>(),
    } as Response);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('sends one expand request when path-A auto-trigger and SSE-trigger overlap', async () => {
    const setUiGeneration = vi.fn();
    const addToast = vi.fn();

    const { result } = renderHook(() =>
      useItineraryGeneration({
        uiGeneration: null,
        setUiGeneration,
        addToast,
        planViewState: 'S2_STRATEGY_READY',
        docExecutedTopics: ['hiking', 'diving'],
        hasDates: true,
        docDayCards: [],
        isRegenerating: false,
        tripInputsStartDate: '2026-03-01',
      })
    );

    act(() => {
      result.current.requestAutoExpandItinerary({ forceFullRebuild: true });
    });

    await act(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
    });

    const expandCalls = mockApiFetch.mock.calls.filter(
      ([path]) => path === '/api/expand-itinerary'
    );
    expect(expandCalls).toHaveLength(1);
  });
});
