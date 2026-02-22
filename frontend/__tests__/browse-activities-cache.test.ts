/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { beforeEach, describe, expect, it, vi } from 'vitest';

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function mockResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: () => Promise.resolve(body),
  } as Response;
}

describe('browseActivities cache behavior', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it('dedupes identical in-flight requests (including reordered categories)', async () => {
    const deferred = createDeferred<Response>();
    const fetchMock = vi.fn().mockReturnValue(deferred.promise);
    vi.stubGlobal('fetch', fetchMock);

    const { browseActivities } = await import('@/lib/api');
    const p1 = browseActivities({
      destination: 'Bali',
      categories: ['Food', 'nature', 'food'],
    });
    const p2 = browseActivities({
      destination: 'Bali',
      categories: ['nature', 'food'],
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);

    deferred.resolve(mockResponse({ tiles: [{ id: 'a' }], total: 1 }));
    const [r1, r2] = await Promise.all([p1, p2]);

    expect(r1).toEqual(r2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('serves cached response for repeated identical request within TTL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ tiles: [{ id: 'cached' }], total: 1 }));
    vi.stubGlobal('fetch', fetchMock);

    const { browseActivities } = await import('@/lib/api');

    const r1 = await browseActivities({
      destination: 'Bali',
      dayNumber: 2,
      date: '2026-06-10',
      categories: ['food', 'nature'],
      hotelLocation: { lat: -8.6701, lng: 115.2102 },
    });
    const r2 = await browseActivities({
      destination: 'Bali',
      dayNumber: 2,
      date: '2026-06-10',
      categories: ['nature', 'food'],
      hotelLocation: { lat: -8.6701, lng: 115.2102 },
    });

    expect(r1).toEqual(r2);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('expires cache after TTL and fetches fresh data', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-01T00:00:00.000Z'));

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(mockResponse({ tiles: [{ id: 'first' }], total: 1 }))
      .mockResolvedValueOnce(mockResponse({ tiles: [{ id: 'second' }], total: 1 }));
    vi.stubGlobal('fetch', fetchMock);

    const { browseActivities } = await import('@/lib/api');
    const params = { destination: 'Bali', categories: ['food'] };

    const first = await browseActivities(params);
    vi.advanceTimersByTime(4 * 60 * 1000);
    const cached = await browseActivities(params);
    vi.advanceTimersByTime(61 * 1000);
    const refreshed = await browseActivities(params);

    expect(first.tiles[0]?.id).toBe('first');
    expect(cached.tiles[0]?.id).toBe('first');
    expect(refreshed.tiles[0]?.id).toBe('second');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
