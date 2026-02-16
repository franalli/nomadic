/**
 * Plan State Helpers
 *
 * Single source of truth for gating functions.
 * Data-driven via envelope.generation, not state-inferred.
 */

import type { GenerationState, PlanViewState } from '@/types/plan-envelope';

// Re-export for convenience
export type { GenerationState };

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
  // Must be in S2_STRATEGY_READY state
  if (state !== 'S2_STRATEGY_READY') return false;

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
  // S2 shows expand_itinerary CTA (NextStepBar gates enabled/disabled via validation)
  if (state === 'S2_STRATEGY_READY') return 'expand_itinerary';
  // S3 uses inline "The Bridge" CTA, not NextStepBar
  return null;
}
