'use client';

import { useSyncExternalStore } from 'react';

/**
 * useIsDesktop - Standalone viewport hook.
 *
 * Returns true when viewport width >= 1024px (Tailwind `lg` breakpoint).
 * Replaces the isDesktop field from the former MobileModeContext.
 *
 * Uses useSyncExternalStore for SSR-safe, tear-free reads of matchMedia.
 */

const query = '(min-width: 1024px)';

const mq =
  typeof window !== 'undefined' ? window.matchMedia(query) : null;

function subscribe(callback: () => void) {
  mq?.addEventListener('change', callback);
  return () => mq?.removeEventListener('change', callback);
}

function getSnapshot() {
  return mq?.matches ?? false;
}

function getServerSnapshot() {
  return false;
}

export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
