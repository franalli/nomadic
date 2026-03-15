import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api', () => ({ apiFetch: vi.fn() }));

function mockResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

async function loadUserStore() {
  vi.resetModules();
  const { apiFetch } = await import('@/lib/api');
  const { useUserStore } = await import('@/state/userStore');

  return {
    useUserStore,
    mockApiFetch: vi.mocked(apiFetch),
  };
}

describe('userStore.fetchUser', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('dedupes concurrent fetches and reuses the fresh result briefly', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-13T10:00:00Z'));

    const { useUserStore, mockApiFetch } = await loadUserStore();

    let resolveFetch: ((value: Response) => void) | null = null;
    mockApiFetch.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        })
    );

    const p1 = useUserStore.getState().fetchUser();
    const p2 = useUserStore.getState().fetchUser();

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(resolveFetch).not.toBeNull();

    resolveFetch!(
      mockResponse(200, {
        user: { id: 1, email: 'traveler@example.com', name: 'Traveler', avatar_url: null },
      })
    );

    await Promise.all([p1, p2]);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(useUserStore.getState().user?.email).toBe('traveler@example.com');

    await useUserStore.getState().fetchUser();

    expect(mockApiFetch).toHaveBeenCalledTimes(1);

    vi.setSystemTime(new Date('2026-03-13T10:00:06Z'));
    mockApiFetch.mockResolvedValueOnce(
      mockResponse(200, {
        user: { id: 1, email: 'traveler@example.com', name: 'Traveler', avatar_url: null },
      })
    );

    await useUserStore.getState().fetchUser();

    expect(mockApiFetch).toHaveBeenCalledTimes(2);
  });

  it('retries immediately after a failed auth fetch instead of caching the failure', async () => {
    const { useUserStore, mockApiFetch } = await loadUserStore();

    mockApiFetch
      .mockResolvedValueOnce(mockResponse(503, { detail: 'Temporary failure' }))
      .mockResolvedValueOnce(
        mockResponse(200, {
          user: { id: 7, email: 'retry@example.com', name: 'Retry', avatar_url: null },
        })
      );

    await useUserStore.getState().fetchUser();

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(useUserStore.getState().loading).toBe(false);
    expect(useUserStore.getState().user).toBeNull();

    await useUserStore.getState().fetchUser();

    expect(mockApiFetch).toHaveBeenCalledTimes(2);
    expect(useUserStore.getState().user?.email).toBe('retry@example.com');
  });
});
