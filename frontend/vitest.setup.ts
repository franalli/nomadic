/* eslint no-unused-vars: ["error", { "args": "none" }] */
import '@testing-library/jest-dom/vitest';

import { afterEach, beforeEach, vi } from 'vitest';

// Mock Next.js navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

if (typeof window.IntersectionObserver === 'undefined') {
  class MockIntersectionObserver implements IntersectionObserver {
    readonly root: Element | null = null;
    readonly rootMargin: string = '';
    readonly thresholds: ReadonlyArray<number> = [];

    constructor(public readonly callback: IntersectionObserverCallback) {}

    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn((): IntersectionObserverEntry[] => []);
  }

  // Attach mock to the test window
  (
    window as unknown as { IntersectionObserver: typeof IntersectionObserver }
  ).IntersectionObserver = MockIntersectionObserver;
}

if (!globalThis.crypto) {
  globalThis.crypto = {
    randomUUID: () => 'test-session-id',
  } as Crypto;
}

process.env.NEXT_PUBLIC_API_URL = 'http://test.local';

beforeEach(() => {
  // Node 25+ native localStorage may lack clear(); guard for compat
  if (typeof localStorage.clear === 'function') {
    localStorage.clear();
  } else {
    for (const key of Object.keys(localStorage)) {
      localStorage.removeItem(key);
    }
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});
