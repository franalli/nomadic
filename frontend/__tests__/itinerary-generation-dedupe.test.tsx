import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));
vi.mock('@/lib/streamParser', () => ({ consumeNdjsonEnvelopeStream: vi.fn() }));

import { useItineraryGeneration } from '@/components/layout/hooks/useItineraryGeneration';
import { apiFetch } from '@/lib/api';
import { consumeNdjsonEnvelopeStream } from '@/lib/streamParser';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

const mockApiFetch = vi.mocked(apiFetch);
const mockConsumeNdjsonEnvelopeStream = vi.mocked(consumeNdjsonEnvelopeStream);

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

const CONFLICT_DAY_CARD = {
  day_number: 1,
  label: 'Arrival + light activity',
  blocks: [],
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
    mockConsumeNdjsonEnvelopeStream.mockImplementation(
      async (_body, callbacks: Record<string, unknown>) => {
        const onDone = callbacks.onDone as
          | ((
              event: {
                type: 'done';
                plan_view_state: 'S3_ITINERARY_READY';
                version: number;
              }
            ) => void)
          | undefined;
        onDone?.({ type: 'done', plan_view_state: 'S3_ITINERARY_READY', version: 2 });
      }
    );
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

  it('uses backend conflict plan_view_state from the expand payload', async () => {
    mockConsumeNdjsonEnvelopeStream.mockImplementationOnce(
      async (_body, callbacks: Record<string, unknown>) => {
        const onError = callbacks.onError as
          | ((event: { type: 'error'; message: string }) => void)
          | undefined;
        onError?.({
          type: 'error',
          message: JSON.stringify({
            error: 'CONSTRAINT_CONFLICT',
            plan_view_state: 'S3_PARTIAL_CONFLICT',
            day_cards: [CONFLICT_DAY_CARD],
          }),
        });
      }
    );

    const { result } = renderHook(() =>
      useItineraryGeneration({
        uiGeneration: null,
        setUiGeneration: vi.fn(),
        addToast: vi.fn(),
        planViewState: 'S2_STRATEGY_READY',
        docExecutedTopics: ['hiking'],
        hasDates: true,
        docDayCards: [],
        isRegenerating: false,
        tripInputsStartDate: '2026-03-01',
      })
    );

    await act(async () => {
      await result.current.proceedWithItineraryGeneration();
    });

    expect(useDocumentStore.getState().document?.plan_view_state).toBe(
      'S3_PARTIAL_CONFLICT'
    );
    expect(useDocumentStore.getState().document?.day_cards).toEqual([
      expect.objectContaining(CONFLICT_DAY_CARD),
    ]);
  });

  it('does not fabricate a conflict plan_view_state when the payload omits it', async () => {
    mockConsumeNdjsonEnvelopeStream.mockImplementationOnce(
      async (_body, callbacks: Record<string, unknown>) => {
        const onError = callbacks.onError as
          | ((event: { type: 'error'; message: string }) => void)
          | undefined;
        onError?.({
          type: 'error',
          message: JSON.stringify({
            error: 'CONSTRAINT_CONFLICT',
            day_cards: [CONFLICT_DAY_CARD],
          }),
        });
      }
    );

    const { result } = renderHook(() =>
      useItineraryGeneration({
        uiGeneration: null,
        setUiGeneration: vi.fn(),
        addToast: vi.fn(),
        planViewState: 'S2_STRATEGY_READY',
        docExecutedTopics: ['hiking'],
        hasDates: true,
        docDayCards: [],
        isRegenerating: false,
        tripInputsStartDate: '2026-03-01',
      })
    );

    await act(async () => {
      await result.current.proceedWithItineraryGeneration();
    });

    expect(useDocumentStore.getState().document?.plan_view_state).toBe(
      'S2_STRATEGY_READY'
    );
    expect(useDocumentStore.getState().document?.day_cards).toEqual([
      expect.objectContaining(CONFLICT_DAY_CARD),
    ]);
  });
});
