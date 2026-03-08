/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * Plan State Helpers
 *
 * Single source of truth for gating functions.
 * Data-driven via envelope.generation, not state-inferred.
 */

import type { GenerationState, PlanViewState } from '@/types/plan-envelope';
import { normalizePlanViewState } from '@/types/plan-envelope';

// Re-export for convenience
export type { GenerationState };

// ─────────────────────────────────────────────────────────────────────────────
// Shared state constant sets — use these instead of inline literal arrays
// ─────────────────────────────────────────────────────────────────────────────

/** States where booking actions are available */
export const BOOKABLE_STATES: ReadonlySet<string> = new Set([
  "S3_ITINERARY_READY", "P3_FINALIZED",
]);

/** States where a plan is actively being worked on */
export const PLAN_ACTIVE_STATES: ReadonlySet<string> = new Set([
  "S2_STRATEGY_READY", "S2_BLOCKED", "S3_ITINERARY_READY", "S3_BLOCKED", "S3_EDITING", "S3_PARTIAL_CONFLICT",
  "P0_MINIMAL", "P1_ENRICHED", "P2_LOGISTICS", "P3_BLOCKED", "P3_EDITING", "P3_FINALIZED",
]);

/** States where itinerary data is expected to exist */
export const ITINERARY_STATES: ReadonlySet<string> = new Set([
  "S3_BLOCKED", "S3_EDITING", "S3_ITINERARY_READY", "S3_PARTIAL_CONFLICT",
  "P3_BLOCKED", "P3_EDITING", "P3_FINALIZED",
]);

// ─────────────────────────────────────────────────────────────────────────────
// State predicates — use these instead of raw string comparisons
// ─────────────────────────────────────────────────────────────────────────────

/** Is the plan in the initial bootstrap/empty phase? (P0_MINIMAL or any legacy S0/S1 alias) */
export function isBootstrap(state: PlanViewState | undefined | null): boolean {
  if (!state) return true;
  return normalizePlanViewState(state) === 'P0_MINIMAL';
}

/** Is the plan in the strategy-ready phase? (P1_ENRICHED or legacy S2_STRATEGY_READY) */
export function isStrategyReady(state: PlanViewState | undefined | null): boolean {
  if (!state) return false;
  return normalizePlanViewState(state) === 'P1_ENRICHED' && state !== 'S2_BLOCKED';
}

/** Is the plan in itinerary-ready/finalized state? */
export function isItineraryReady(state: PlanViewState | undefined | null): boolean {
  if (!state) return false;
  const norm = normalizePlanViewState(state);
  return norm === 'P3_FINALIZED';
}

/** Is the plan in an editing state? */
export function isEditing(state: PlanViewState | undefined | null): boolean {
  if (!state) return false;
  const norm = normalizePlanViewState(state);
  return norm === 'P3_EDITING';
}

/** Is generation in progress? Data-driven, not state-inferred. */
export function isGenerating(generation?: GenerationState | null): boolean {
  return generation?.active === true;
}

/**
 * Should auto-trigger itinerary generation? (Path A UX)
 *
 * Auto-trigger when:
 * - S2_STRATEGY_READY (strategy complete)
 * - Multi-specialist trip (2+ specialists executed)
 * - Has valid dates (start + end)
 * - Not currently generating
 *
 * @see docs/ux_unified_architecture.md - Path A: Auto-trigger Flow
 */
export function shouldAutoTriggerItinerary(
  state: PlanViewState,
  executedTopics: string[] | undefined,
  hasDates: boolean,
  generation?: GenerationState | null,
  hasItineraryContent?: boolean
): boolean {
  // Must be in strategy-ready state (S2 / P1_ENRICHED)
  if (!isStrategyReady(state)) return false;

  // Must not be currently generating
  if (isGenerating(generation)) return false;

  // Must have dates set
  if (!hasDates) return false;

  // Must be multi-specialist (2+ topics executed)
  const topicCount = executedTopics?.length ?? 0;
  if (topicCount < 2) return false;

  // Must not already have itinerary content
  if (hasItineraryContent) return false;

  return true;
}

/**
 * Is this a multi-specialist trip?
 * Used for UI variations (auto-trigger vs manual button).
 */
export function isMultiSpecialistTrip(executedTopics: string[] | undefined): boolean {
  return (executedTopics?.length ?? 0) >= 2;
}

/**
 * Get next action for NextStepBar (null = no CTA).
 * Compute ONCE in parent and pass to NextStepBar to avoid flicker.
 *
 * Note: S3_ITINERARY_READY returns null because "The Bridge" CTA
 * is rendered inline at the bottom of the timeline, not in NextStepBar.
 *
 * IMPORTANT: Returns action type based on state alone. NextStepBar handles
 * validation gating (disabled state + messaging).
 */
export function getNextAction(
  state: PlanViewState,
  generation?: GenerationState | null,

  _hasTripContext?: boolean // Deprecated: validation now handled by NextStepBar
): 'expand_itinerary' | 'finalize_plan' | null {
  if (isGenerating(generation)) return null;
  // Strategy-ready shows expand_itinerary CTA (NextStepBar gates enabled/disabled via validation)
  if (isStrategyReady(state)) return 'expand_itinerary';
  // Itinerary-ready uses inline "The Bridge" CTA, not NextStepBar
  return null;
}
