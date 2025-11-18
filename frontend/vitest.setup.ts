import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

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

if (!globalThis.crypto) {
  globalThis.crypto = {
    randomUUID: () => 'test-session-id',
  } as Crypto;
}

process.env.NEXT_PUBLIC_API_URL = 'http://test.local';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});
