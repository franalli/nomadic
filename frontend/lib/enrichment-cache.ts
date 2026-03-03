import type { StrategySection } from '@/types/plan-envelope';

/**
 * Module-level caches for destination intelligence enrichment polling.
 *
 * Shared between PlanFullDensityView (main view) and StrategyHero (sheet).
 * The INFLIGHT map prevents duplicate concurrent polls for the same destination.
 */

export const DESTINATION_INTEL_CACHE = new Map<string, StrategySection>();
export const DESTINATION_INTEL_INFLIGHT = new Map<string, Promise<void>>();
