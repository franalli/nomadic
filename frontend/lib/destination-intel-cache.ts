'use client';

import { getSpecialistEnrichment } from '@/lib/api';
import type { StrategySection } from '@/types/plan-envelope';

// ---------------------------------------------------------------------------
// Module-scope cache + inflight dedup
// ---------------------------------------------------------------------------

const _cache = new Map<string, { section: StrategySection; cachedAt: number }>();
const _inflight = new Map<string, Promise<void>>();
const CACHE_TTL_MS = 30 * 60 * 1000; // 30 minutes
const CACHE_MAX_ENTRIES = 50;

// ---------------------------------------------------------------------------
// Cache helpers
// ---------------------------------------------------------------------------

export function getCachedDestinationIntel(destinationKey: string): StrategySection | null {
  const entry = _cache.get(destinationKey);
  if (!entry) return null;
  if (Date.now() - entry.cachedAt > CACHE_TTL_MS) {
    _cache.delete(destinationKey);
    return null;
  }
  return entry.section;
}

export function setCachedDestinationIntel(destinationKey: string, section: StrategySection): void {
  if (_cache.has(destinationKey)) {
    _cache.delete(destinationKey);
  }
  _cache.set(destinationKey, { section, cachedAt: Date.now() });
  while (_cache.size > CACHE_MAX_ENTRIES) {
    const oldestKey = _cache.keys().next().value;
    if (oldestKey === undefined) break;
    _cache.delete(oldestKey);
  }
}

/** Check whether an inflight poll is already running for the given key. */
export function getInflight(destinationKey: string): Promise<void> | undefined {
  return _inflight.get(destinationKey);
}

/** Register an inflight promise (callers manage the actual polling loop). */
export function setInflight(destinationKey: string, promise: Promise<void>): void {
  _inflight.set(destinationKey, promise);
}

/** Remove the inflight promise for the given key. */
export function deleteInflight(destinationKey: string): void {
  _inflight.delete(destinationKey);
}

/** Normalize a destination string into a stable cache key. */
export function normalizeDestinationKey(destination: string | null | undefined): string {
  return (destination || '').trim().toLowerCase();
}

/**
 * Fetch enrichment for a specialist section by ID, with the same
 * contract as `getSpecialistEnrichment` from api.ts.
 *
 * Re-exported here so consumers only need a single import for
 * cache + fetch.
 */
export { getSpecialistEnrichment };

/** Clear all cache entries and inflight promises (e.g. on session reset / destination change). */
export function clearDestinationIntelCache(): void {
  _cache.clear();
  _inflight.clear();
}
