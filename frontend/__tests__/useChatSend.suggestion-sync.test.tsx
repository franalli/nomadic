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
import type {
  PlanDocumentData,
  SuggestionChip,
  SuggestionChipMeta,
} from '@/types/document';

const CHIPS: SuggestionChip[] = [
  {
    message: 'Add diving',
    action_type: 'send_message',
    chip_type: 'follow_up',
    category: 'activities',
  },
  {
    message: 'Set your dates',
    action_type: 'open_pill',
    action_target: 'dates',
    chip_type: 'setting',
    category: 'dates',
  },
];

const META: SuggestionChipMeta[] = [
  { chip_type: 'follow_up', category: 'activities' },
  { chip_type: 'setting', category: 'dates' },
];

function makeDocument(overrides: Partial<PlanDocumentData> = {}): PlanDocumentData {
  return {
    trip_context_id: null,
    trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Bali' },
    branches: [],
    tiles: {},
    plan_view_state: 'S0_BOOTSTRAP',
    ...overrides,
  };
}

function seedDocument(overrides: Partial<PlanDocumentData> = {}): void {
  useDocumentStore.getState().reset();
  useChatStore.getState().resetChat();
  useDocumentStore.setState({
    version: 1,
    document: makeDocument(overrides),
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

describe('useChatSend document → local suggestion sync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('seeds local state from a hydrated document, deriving suggestedResponses from chip messages', () => {
    // Hydrated doc carries chips + meta but NO suggested_responses — the
    // rendering gate keys off suggestedResponses, so they must be derived.
    seedDocument({ suggestion_chips: CHIPS, suggested_response_meta: META });

    const { result } = renderUseChatSend();

    expect(result.current.suggestionChips).toEqual(CHIPS);
    expect(result.current.suggestedResponses).toEqual(['Add diving', 'Set your dates']);
    expect(result.current.suggestedResponseMeta).toEqual(META);
  });

  it('uses document suggested_responses verbatim when present', () => {
    seedDocument({
      suggestion_chips: CHIPS,
      suggested_responses: ['Custom one', 'Custom two'],
      suggested_response_meta: META,
    });

    const { result } = renderUseChatSend();

    expect(result.current.suggestedResponses).toEqual(['Custom one', 'Custom two']);
  });

  it('does not seed while a send is in flight (isSendingRef true)', () => {
    seedDocument();
    const { result } = renderUseChatSend();

    const refs = mockState.capturedRefs.current as {
      isSendingRef: { current: boolean };
    };
    refs.isSendingRef.current = true;

    act(() => {
      useDocumentStore.getState().setSuggestionChipFields({
        suggestion_chips: CHIPS,
        suggested_responses: ['Add diving', 'Set your dates'],
        suggested_response_meta: META,
      });
    });

    expect(result.current.suggestionChips).toEqual([]);
    expect(result.current.suggestedResponses).toEqual([]);
    expect(result.current.suggestedResponseMeta).toEqual([]);
  });

  it('refreshes local state when document chip fields update out-of-band (expand done)', () => {
    seedDocument();
    const { result } = renderUseChatSend();

    expect(result.current.suggestionChips).toEqual([]);

    act(() => {
      useDocumentStore.getState().setSuggestionChipFields({
        suggestion_chips: CHIPS,
        suggested_responses: ['Add diving', 'Set your dates'],
        suggested_response_meta: META,
      });
    });

    expect(result.current.suggestionChips).toEqual(CHIPS);
    expect(result.current.suggestedResponses).toEqual(['Add diving', 'Set your dates']);
    expect(result.current.suggestedResponseMeta).toEqual(META);
  });

  it('clears local state when the document becomes null (reset)', () => {
    seedDocument({
      suggestion_chips: CHIPS,
      suggested_responses: ['Add diving', 'Set your dates'],
      suggested_response_meta: META,
    });

    const { result } = renderUseChatSend();
    expect(result.current.suggestionChips).toEqual(CHIPS);

    act(() => {
      useDocumentStore.setState({ document: null });
    });

    expect(result.current.suggestionChips).toEqual([]);
    expect(result.current.suggestedResponses).toEqual([]);
    expect(result.current.suggestedResponseMeta).toEqual([]);
  });
});
