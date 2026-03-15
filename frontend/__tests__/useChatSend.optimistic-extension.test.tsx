import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockState = vi.hoisted(() => ({
  executeStreamMock: vi.fn(),
  capturedRefs: { current: null as unknown },
  delayedLoader: {
    startLoading: vi.fn(),
    onTangibleOutput: vi.fn(),
    reset: vi.fn(),
  },
  actionLoader: {
    startLoading: vi.fn(),
    onTangibleOutput: vi.fn(),
    reset: vi.fn(),
  },
}));

vi.mock('@/components/chat/ChatPanel', () => ({
  getSendBurstGuardReason: () => null,
}));

vi.mock('@/hooks/useActionLoader', () => ({
  useActionLoader: () => mockState.actionLoader,
}));

vi.mock('@/hooks/useDelayedLoader', () => ({
  useDelayedLoader: () => mockState.delayedLoader,
}));

vi.mock('@/hooks/useChatSse', () => ({
  useChatSse: (refs: unknown) => {
    mockState.capturedRefs.current = refs;
    return { executeStream: mockState.executeStreamMock };
  },
}));

import { useChatSend } from '@/hooks/useChatSend';
import { useChatStore } from '@/state/chatStore';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';

function seedTripDocument(): void {
  useDocumentStore.getState().reset();
  useChatStore.getState().resetChat();
  useDocumentStore.setState({
    version: 1,
    document: {
      trip_context_id: null,
      trip_inputs: {
        ...DEFAULT_TRIP_INPUTS,
        destination: 'Bali',
        origin: 'Rome',
        start_date: '2026-04-01',
        end_date: '2026-04-04',
        trip_duration: 4,
        activity_settings: {
          ...DEFAULT_TRIP_INPUTS.activity_settings,
          categories: ['diving'],
        },
      },
      branches: [],
      tiles: {},
      strategy_sections: [],
      plan_view_state: 'S3_ITINERARY_READY',
      day_cards: [
        { day_number: 1, date: '2026-04-01', label: 'Day 1', blocks: [] },
        { day_number: 2, date: '2026-04-02', label: 'Day 2', blocks: [] },
        { day_number: 3, date: '2026-04-03', label: 'Day 3', blocks: [] },
        { day_number: 4, date: '2026-04-04', label: 'Day 4', blocks: [] },
      ],
    },
    ensureSettingsFlushed: vi.fn().mockResolvedValue(undefined),
    bumpMessageSendNonce: vi.fn(),
  } as never);
}

function renderUseChatSend() {
  return renderHook(() =>
    useChatSend({
      onPlanResult: vi.fn(),
      onGeneratePlanStart: vi.fn(),
      onAutoExpandItinerary: vi.fn(),
      onUserMessageSubmit: vi.fn(),
      selectedBranchId: null,
      hasBranches: false,
      setGenerateTriggered: vi.fn(),
      setActiveStatus: vi.fn(),
      scrollPanelIntoView: vi.fn(),
      scrollToBottom: vi.fn(),
      inputRef: { current: document.createElement('textarea') },
      toast: vi.fn(),
    })
  );
}

describe('useChatSend optimistic extension rollback', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seedTripDocument();
  });

  it('rolls back optimistic extension cards and dates when the user stops streaming', async () => {
    mockState.executeStreamMock.mockImplementationOnce(
      async () =>
        new Promise<'stale'>(() => {
          const refs = mockState.capturedRefs.current as {
            abortStreamRef: { current: null | (() => void) };
          };
          refs.abortStreamRef.current = () => undefined;
        })
    );

    const { result } = renderUseChatSend();

    await act(async () => {
      void result.current.sendMessageCore('extend by 2 days');
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(useDocumentStore.getState().document?.trip_inputs.end_date).toBe('2026-04-06');
    expect(useDocumentStore.getState().document?.day_cards).toHaveLength(6);

    await act(async () => {
      result.current.handleStopStreaming();
      await Promise.resolve();
    });

    expect(useDocumentStore.getState().document?.trip_inputs.end_date).toBe('2026-04-04');
    expect(useDocumentStore.getState().document?.trip_inputs.trip_duration).toBe(4);
    expect(useDocumentStore.getState().document?.day_cards).toHaveLength(4);
  });

  it('rolls back optimistic extension when the stream errors before completion', async () => {
    mockState.executeStreamMock.mockResolvedValueOnce('error');

    const { result } = renderUseChatSend();

    await act(async () => {
      await result.current.sendMessageCore('extend by 2 days');
    });

    expect(useDocumentStore.getState().document?.trip_inputs.end_date).toBe('2026-04-04');
    expect(useDocumentStore.getState().document?.trip_inputs.trip_duration).toBe(4);
    expect(useDocumentStore.getState().document?.day_cards).toHaveLength(4);
  });

  it('uses canonical trip inputs on the next request after an optimistic extension is aborted', async () => {
    const sentBodies: Array<{ trip_inputs?: { end_date?: string | null; trip_duration?: number | null } }> =
      [];

    mockState.executeStreamMock
      .mockImplementationOnce(
        async () =>
          new Promise<'stale'>(() => {
            const refs = mockState.capturedRefs.current as {
              abortStreamRef: { current: null | (() => void) };
            };
            refs.abortStreamRef.current = () => undefined;
          })
      )
      .mockImplementationOnce(async ({ body }: { body: { trip_inputs?: { end_date?: string | null; trip_duration?: number | null } } }) => {
        sentBodies.push(body);
        return 'complete';
      });

    const { result } = renderUseChatSend();

    await act(async () => {
      void result.current.sendMessageCore('extend by 2 days');
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      result.current.handleStopStreaming();
      await Promise.resolve();
    });

    await act(async () => {
      await result.current.sendMessageCore('change hotel');
    });

    expect(sentBodies).toHaveLength(1);
    expect(sentBodies[0]?.trip_inputs?.end_date).toBe('2026-04-04');
    expect(sentBodies[0]?.trip_inputs?.trip_duration).toBe(4);
  });

  it('keeps the optimistic extension applied when a successful stream regresses the document back to the pre-extension dates', async () => {
    mockState.executeStreamMock.mockImplementationOnce(async () => {
      useDocumentStore.getState().mergeEnvelope({
        trip_inputs: {
          end_date: '2026-04-04',
          trip_duration: 4,
        },
        day_cards: [
          { day_number: 1, date: '2026-04-01', label: 'Day 1', blocks: [] },
          { day_number: 2, date: '2026-04-02', label: 'Day 2', blocks: [] },
          { day_number: 3, date: '2026-04-03', label: 'Day 3', blocks: [] },
          { day_number: 4, date: '2026-04-04', label: 'Day 4', blocks: [] },
        ],
      });
      return 'complete';
    });

    const { result } = renderUseChatSend();

    await act(async () => {
      await result.current.sendMessageCore('extend by 2 days');
    });

    expect(useDocumentStore.getState().document?.trip_inputs.end_date).toBe('2026-04-06');
    expect(useDocumentStore.getState().document?.trip_inputs.trip_duration).toBe(6);
    expect(useDocumentStore.getState().document?.day_cards).toHaveLength(6);
  });
});
