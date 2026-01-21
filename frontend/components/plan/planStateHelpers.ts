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

/** Can user view booking tiles? (primary display in S3) */
export function canShowBookingTiles(state: PlanViewState): boolean {
  return state === 'S3_ITINERARY_READY';
}

/** Can show tiles preview? (collapsed in S2 if tiles exist) */
export function canShowTilesPreview(state: PlanViewState, tileCount: number): boolean {
  return state.startsWith('S2_') && tileCount > 0;
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
 * hasTripContext gates 'expand_itinerary' action.
 * Compute ONCE in parent and pass to NextStepBar to avoid flicker.
 */
export function getNextAction(
  state: PlanViewState,
  generation?: GenerationState | null,
  hasTripContext?: boolean
): 'expand_itinerary' | 'view_booking' | null {
  if (isGenerating(generation)) return null;
  // Gate expand_itinerary on hasTripContext
  if (state === 'S2_STRATEGY_READY' && hasTripContext) return 'expand_itinerary';
  if (state === 'S3_ITINERARY_READY') return 'view_booking';
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
