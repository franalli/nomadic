import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useTripInputsWithFallback } from '@/hooks/useTripInputsWithFallback';
import { DEFAULT_TRIP_INPUTS, useDocumentStore } from '@/state/documentStore';
import type { PlanDocumentData } from '@/types/document';

function makeDoc(overrides: Partial<PlanDocumentData> = {}): PlanDocumentData {
  return {
    trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon' },
    branches: [],
    tiles: {},
    plan_view_state: 'S0_BOOTSTRAP',
    ...overrides,
  };
}

describe('useTripInputsWithFallback', () => {
  beforeEach(() => {
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
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns prop inputs without subscribing to the document store', () => {
    const subscribeSpy = vi.spyOn(useDocumentStore, 'subscribe');
    const propInputs = { ...DEFAULT_TRIP_INPUTS, destination: 'Rome' };

    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Lisbon' },
      }),
    });

    const { result } = renderHook(() => useTripInputsWithFallback(propInputs));

    expect(result.current).toBe(propInputs);
    expect(subscribeSpy).not.toHaveBeenCalled();

    act(() => {
      useDocumentStore.setState({
        document: makeDoc({
          trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Paris' },
        }),
      });
    });

    expect(result.current).toBe(propInputs);
    expect(subscribeSpy).not.toHaveBeenCalled();
  });

  it('falls back to live store inputs when props are absent', () => {
    const subscribeSpy = vi.spyOn(useDocumentStore, 'subscribe');

    useDocumentStore.setState({
      document: makeDoc({
        trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Tokyo' },
      }),
    });

    const { result } = renderHook(() => useTripInputsWithFallback());

    expect(result.current?.destination).toBe('Tokyo');
    expect(subscribeSpy).toHaveBeenCalled();

    act(() => {
      useDocumentStore.setState({
        document: makeDoc({
          trip_inputs: { ...DEFAULT_TRIP_INPUTS, destination: 'Seoul' },
        }),
      });
    });

    expect(result.current?.destination).toBe('Seoul');
  });
});
