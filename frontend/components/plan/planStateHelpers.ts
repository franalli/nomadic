/**
 * Plan State Helpers
 *
 * Single source of truth for gating functions.
 * Data-driven via envelope.generation, not state-inferred.
 */

import type { GenerationState,PlanViewState } from '@/types/plan-envelope';

// Re-export for convenience
export type { GenerationState };

/** Is generation in progress? Data-driven, not state-inferred. */
export function isGenerating(generation?: GenerationState | null): boolean {
  return generation?.active === true;
}

/** Is the plan in a ready state (not generating, not blocked)? */
export function isReady(state: PlanViewState, generation?: GenerationState | null): boolean {
  if (isGenerating(generation)) return false;
  return state === 'S2_STRATEGY_READY' || state === 'S3_ITINERARY_READY';
}

/**
 * Can user expand to itinerary?
 * Requires S2 ready + trip context exists + not generating.
 * hasTripContext is the single source of truth for trip_context_id check.
 */
export function canExpandToItinerary(
  state: PlanViewState,
  generation?: GenerationState | null,
  hasTripContext?: boolean
): boolean {
  if (!hasTripContext) return false;
  return state === 'S2_STRATEGY_READY' && !isGenerating(generation);
}

/**
 * Can user view booking tiles? (primary display in S3)
 * @deprecated Use `effectiveMode === 'booking'` instead.
 * State-based check replaced by mode-based check per two-mode system.
 * @see docs/ux_unified_architecture.md Section I.B - Mode is SSoT for UI variant
 */
export function canShowBookingTiles(state: PlanViewState): boolean {
  return state === 'S3_ITINERARY_READY';
}

/**
 * Can show tiles preview? When S2 READY and has tiles, not generating.
 * Strategy content check removed - tiles should show as soon as available.
 * @deprecated Use `effectiveMode === 'planning' && tileCount > 0 && !isGenerating(generation)` instead.
 * State-based check replaced by mode-based check per two-mode system.
 * @see docs/ux_unified_architecture.md Section I.B - Mode is SSoT for UI variant
 */
export function canShowTilesPreview(
  state: PlanViewState,
  tileCount: number,
  generation?: GenerationState | null,
  _hasStrategyContent?: boolean
): boolean {
  void _hasStrategyContent; // Unused - tiles show regardless of strategy sections
  return (
    state === 'S2_STRATEGY_READY' &&
    tileCount > 0 &&
    !isGenerating(generation)
  );
}

/** Get the appropriate stage label */
export function getStageFromState(state: PlanViewState): 'bootstrap' | 'structure' | 'strategy' | 'itinerary' {
  if (state === 'S0_BOOTSTRAP') return 'bootstrap';
  if (state === 'S1_FRAMING') return 'structure';
  if (state.startsWith('S2_')) return 'strategy';
  return 'itinerary';
}

/**
 * Get next action for NextStepBar (null = no CTA).
 * Compute ONCE in parent and pass to NextStepBar to avoid flicker.
 *
 * Note: S3_ITINERARY_READY returns null because "The Bridge" CTA
 * is rendered inline at the bottom of the timeline, not in NextStepBar.
 *
 * IMPORTANT: Returns action type based on state alone. NextStepBar handles
 * validation gating (disabled state + messaging) via useTripValidation hook.
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

/**
 * Should left panel show generate CTA?
 * False after plan exists (S2+) - NextStepBar takes over.
 */
export function shouldShowLeftPanelGenerateCTA(state?: PlanViewState): boolean {
  if (!state) return true;
  return state === 'S0_BOOTSTRAP' || state === 'S1_FRAMING';
}
