import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';

describe('MapErrorBoundary', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('schedules and executes auto-recovery for recoverable errors', async () => {
    const boundary = new MapErrorBoundary({ children: null });
    const setStateSpy = vi.spyOn(boundary, 'setState');

    boundary.state = { hasError: true, error: new Error('errorCb is not a function') };
    boundary.componentDidUpdate({ children: null }, { hasError: false, error: null });

    expect(setStateSpy).not.toHaveBeenCalled();
    await vi.runAllTimersAsync();
    expect(setStateSpy).toHaveBeenCalledWith({ hasError: false, error: null });
  });

  it('clears recovery timer on unmount', async () => {
    const boundary = new MapErrorBoundary({ children: null });
    const setStateSpy = vi.spyOn(boundary, 'setState');
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout');

    boundary.state = { hasError: true, error: new Error('Map container is already removed') };
    boundary.componentDidUpdate({ children: null }, { hasError: false, error: null });
    boundary.componentWillUnmount();

    expect(clearTimeoutSpy).toHaveBeenCalled();
    await vi.runAllTimersAsync();
    expect(setStateSpy).not.toHaveBeenCalledWith({ hasError: false, error: null });
  });
});
