import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockState = vi.hoisted(() => ({
  trackEvent: vi.fn(),
  fetchUser: vi.fn(),
  fetchTrips: vi.fn(),
  resumeTrip: vi.fn(),
  user: null as unknown,
  trips: [] as unknown[],
}));

vi.mock('@/lib/analytics', () => ({
  trackEvent: mockState.trackEvent,
}));

vi.mock('@/lib/api', () => ({
  fetchWithRetry: vi.fn(),
}));

vi.mock('@/state/userStore', () => ({
  useUserStore: {
    getState: () => ({
      user: mockState.user,
      trips: mockState.trips,
      fetchUser: mockState.fetchUser,
      fetchTrips: mockState.fetchTrips,
      resumeTrip: mockState.resumeTrip,
    }),
  },
}));

vi.mock('@/components/layout/hooks/useTileSelection', () => ({
  selectionsToTileSelection: vi.fn(() => ({})),
}));

vi.mock('@/lib/debug', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/debug')>();
  return {
    ...actual,
    debugLog: vi.fn(),
  };
});

import { useSessionHydration } from '@/components/layout/hooks/useSessionHydration';

const SESSION_TIMESTAMP_KEY = 'nomadic-session-timestamp';
const STALE_TIMESTAMP = String(Date.now() - 48 * 60 * 60 * 1000); // 48h old

// jsdom in this harness does not provide a working localStorage, so install a
// minimal in-memory shim. The hook only uses getItem/setItem/removeItem.
function installLocalStorageShim() {
  const store = new Map<string, string>();
  const shim: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
  };
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    writable: true,
    value: shim,
  });
}

function createOptions(fetchDocument: ReturnType<typeof vi.fn>) {
  return {
    fetchDocument,
    setBranches: vi.fn(),
    setTilesMap: vi.fn(),
    setBranchSelections: vi.fn(),
    setSelectedBranchId: vi.fn(),
    setTilesBranchId: vi.fn(),
    onToast: vi.fn(),
  } as unknown as Parameters<typeof useSessionHydration>[0];
}

describe('useSessionHydration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installLocalStorageShim();
    localStorage.clear();
    mockState.user = null;
    mockState.trips = [];
    mockState.fetchUser.mockResolvedValue(undefined);
    mockState.fetchTrips.mockResolvedValue(undefined);
    mockState.resumeTrip.mockResolvedValue(false);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('calls fetchDocument even when the localStorage timestamp is stale (>24h)', async () => {
    // A returning unauthenticated browser whose timestamp is >24h old must NOT
    // be gated out of hydration — the backend cookie + persisted doc decide
    // session validity. Stale timestamp must never blank a valid backend doc.
    localStorage.setItem(SESSION_TIMESTAMP_KEY, STALE_TIMESTAMP);
    const fetchDocument = vi.fn().mockResolvedValue(null);

    renderHook(() => useSessionHydration(createOptions(fetchDocument)));

    await waitFor(() => {
      expect(fetchDocument).toHaveBeenCalledTimes(1);
    });
  });

  it('calls fetchDocument when no timestamp exists (fresh browser)', async () => {
    const fetchDocument = vi.fn().mockResolvedValue(null);

    renderHook(() => useSessionHydration(createOptions(fetchDocument)));

    await waitFor(() => {
      expect(fetchDocument).toHaveBeenCalledTimes(1);
    });
  });

  it('restores branches from a backend document despite a stale timestamp', async () => {
    localStorage.setItem(SESSION_TIMESTAMP_KEY, STALE_TIMESTAMP);
    const restoredDoc = {
      trip_context_id: 1,
      branches: [
        {
          id: 'branch-1',
          is_primary: true,
          selections: {},
          tiles: { stays: [{}], flights: [], activities: [] },
        },
      ],
      tiles: {},
    };
    const fetchDocument = vi.fn().mockResolvedValue(restoredDoc);
    const options = createOptions(fetchDocument);

    renderHook(() => useSessionHydration(options));

    await waitFor(() => {
      expect(fetchDocument).toHaveBeenCalledTimes(1);
    });
    // Stale timestamp did not short-circuit: the backend doc's branches are
    // applied to local state.
    await waitFor(() => {
      expect(options.setBranches).toHaveBeenCalledWith(restoredDoc.branches);
    });
    expect(options.setSelectedBranchId).toHaveBeenCalledWith('branch-1');
  });
});
