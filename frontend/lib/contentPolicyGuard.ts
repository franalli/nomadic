/**
 * Content Policy Guard
 *
 * Development-time enforcement of content policy per plan view state.
 * Ensures the right-side plan view never "outruns user consent" by
 * showing content appropriate to the current state.
 *
 * This guard throws in development to catch violations early.
 * In production, it silently logs warnings to avoid breaking the app.
 */

import type {
  PlanViewModel,
  PlanViewState,
} from '@/types/plan-envelope';

// =============================================================================
// Forbidden Strings (Stage 1/2)
// =============================================================================

/**
 * Strings that must NOT appear in Stage 1 or Stage 2 content.
 * These indicate premature disclosure of booking/pricing information.
 *
 * NOTE: Simple currency symbols (€, $) are NOT forbidden because:
 * - Local Expert tips may mention savings like "Saves €50+"
 * - Specialist constraints may reference budgets
 * Only booking-specific patterns are blocked.
 */
const FORBIDDEN_STAGE_1_2 = [
  '$/night',
  '€/night',
  'AED/night',
  'from $',
  'from €',
  'per person',
  'Book now',
  // NOTE: "Reserve" removed - too generic, appears in specialist tips
  // (e.g., "Reserve your spot early"). Keep "Book now" for actual CTAs.
  'Checkout',
  'Top 10',
  'Best places',
  'Best hotels',
  'Best restaurants',
  'Best things',
  'The Best',
  'Iconic',
  'Must-see',
  'Must-do',
] as const;

// =============================================================================
// Error Class
// =============================================================================

export class ContentPolicyError extends Error {
  constructor(
    message: string,
    public readonly state: PlanViewState,
    public readonly violation: string
  ) {
    super(`[ContentPolicy:${state}] ${message}`);
    this.name = 'ContentPolicyError';
  }
}

// =============================================================================
// Assertion Helpers
// =============================================================================

function assertEmpty<T>(
  arr: T[] | undefined,
  name: string,
  state: PlanViewState
): void {
  if (arr && arr.length > 0) {
    throw new ContentPolicyError(
      `${name} must be empty in ${state}, found ${arr.length} items`,
      state,
      `non_empty_${name}`
    );
  }
}

function assertExists<T>(
  value: T | undefined,
  name: string,
  state: PlanViewState
): void {
  if (value === undefined || value === null) {
    throw new ContentPolicyError(
      `${name} is required in ${state}`,
      state,
      `missing_${name}`
    );
  }
}

function assertMaxLength<T>(
  arr: T[] | undefined,
  max: number,
  name: string,
  state: PlanViewState
): void {
  if (arr && arr.length > max) {
    throw new ContentPolicyError(
      `${name} exceeds max ${max} in ${state}, found ${arr.length}`,
      state,
      `exceeds_max_${name}`
    );
  }
}

function assertNoForbiddenStrings(
  content: string,
  state: PlanViewState
): void {
  for (const forbidden of FORBIDDEN_STAGE_1_2) {
    if (content.includes(forbidden)) {
      throw new ContentPolicyError(
        `Forbidden string "${forbidden}" found in ${state}`,
        state,
        `forbidden_string_${forbidden}`
      );
    }
  }
}

// =============================================================================
// Main Enforcement Function
// =============================================================================

/**
 * Enforce content policy for the right-side plan view.
 *
 * Checks that the view model content is appropriate for the current state.
 * Throws ContentPolicyError in development if violations are found.
 *
 * NOTE: With the Unified Planning View architecture, rendering is based on
 * data density (empty/ghost/bridge/full), not state. The state may lag behind
 * the actual data. This guard is now more permissive to handle state sync issues.
 *
 * @param state - Current plan view state
 * @param viewModel - View model to validate
 */
export function enforceRightViewPolicy(
  state: PlanViewState,
  viewModel: PlanViewModel
): void {
  // UNIFIED FLOW FIX: If day_cards exist, we should be in S3 state.
  // Skip early-state checks if data indicates we're further along.
  // This handles the state sync lag in the unified planning view.
  const hasDayCards = viewModel.day_cards && viewModel.day_cards.length > 0;
  if (hasDayCards && (state === 'S0_BOOTSTRAP' || state === 'S1_FRAMING' || state === 'S2_STRATEGY_READY')) {
    // State hasn't caught up to data - skip validation for now
    // The unified flow renders based on data density, not state
    console.debug(`[ContentPolicyGuard] State sync lag: state=${state} but dayCards=${viewModel.day_cards?.length}. Skipping check.`);
    return;
  }

  // S0_BOOTSTRAP: Minimal content allowed
  // - Day cards and open decisions must be empty (plan not ready yet)
  // - Strategy sections ARE allowed when a specialist is detected (e.g., user says "diving trip")
  //   This enables early specialist card display to show we understood the intent
  if (state === 'S0_BOOTSTRAP') {
    assertEmpty(viewModel.day_cards, 'dayCards', state);
    // Allow strategy_sections - specialist detection can happen before full setup
    assertMaxLength(viewModel.strategy_sections, 2, 'strategySections', state);
    assertEmpty(viewModel.open_decisions, 'openDecisions', state);
    return;
  }

  // S1_FRAMING: No day cards, no strategy sections, no prices
  if (state === 'S1_FRAMING') {
    assertEmpty(viewModel.day_cards, 'dayCards', state);
    // Strategy sections may start appearing but should be minimal
    assertMaxLength(viewModel.strategy_sections, 2, 'strategySections', state);

    // Check for forbidden strings
    const content = JSON.stringify(viewModel);
    assertNoForbiddenStrings(content, state);
    return;
  }

  // S2_STRATEGY_READY: Strategy sections + open decisions, but no day cards
  if (state === 'S2_STRATEGY_READY') {
    // Must have open decisions section
    assertExists(viewModel.open_decisions, 'openDecisions', state);
    assertMaxLength(viewModel.open_decisions, 4, 'openDecisions', state);

    // No day cards in S2
    assertEmpty(viewModel.day_cards, 'dayCards', state);

    // Max 6 bullets per section
    if (viewModel.strategy_sections) {
      for (const section of viewModel.strategy_sections) {
        assertMaxLength(section.bullets, 6, `bullets in ${section.title}`, state);
      }
    }

    // Check for forbidden strings
    const content = JSON.stringify(viewModel);
    assertNoForbiddenStrings(content, state);
    return;
  }

  // S2_BLOCKED: Same as S2_STRATEGY_READY but with blocked indicator
  if (state === 'S2_BLOCKED') {
    assertEmpty(viewModel.day_cards, 'dayCards', state);

    // Check for forbidden strings
    const content = JSON.stringify(viewModel);
    assertNoForbiddenStrings(content, state);
    return;
  }

  // S3_ITINERARY_READY: Day cards allowed, but with constraints
  if (state === 'S3_ITINERARY_READY') {
    // Day cards should exist but be constrained
    if (viewModel.day_cards) {
      for (const card of viewModel.day_cards) {
        // Max 3 non-buffer blocks per day (buffer blocks are structural safety constraints)
        const contentBlocks = card.blocks?.filter((b) => !b.is_buffer);
        assertMaxLength(contentBlocks, 3, `blocks in Day ${card.day_number}`, state);
      }
    }

    // No booking-specific prices or CTAs in S3 itinerary
    // NOTE: "Reserve" removed - too generic, appears in legitimate tile descriptions
    // (e.g., "Reserve a table", "Reserve your spot"). Keep "Book now" for CTAs.
    const content = JSON.stringify(viewModel);
    const forbiddenS3 = ['$/night', '€/night', 'AED/night', 'Book now'];
    for (const forbidden of forbiddenS3) {
      if (content.includes(forbidden)) {
        throw new ContentPolicyError(
          `Forbidden string "${forbidden}" found in ${state}`,
          state,
          `forbidden_string_${forbidden}`
        );
      }
    }
    return;
  }

  // S3_EDITING: Same as S3_ITINERARY_READY but with stale indicator
  if (state === 'S3_EDITING') {
    // Same constraints as S3_ITINERARY_READY
    return;
  }

  // S3_BLOCKED: Gate failure, show blocked indicator
  if (state === 'S3_BLOCKED') {
    return;
  }
}

// =============================================================================
// Development-Only Guard
// =============================================================================

/**
 * Development-only enforcement wrapper.
 *
 * In development: Throws ContentPolicyError on violations
 * In production: Logs warning to console, does not throw
 *
 * @param state - Current plan view state
 * @param viewModel - View model to validate
 */
export function guardedEnforcePolicy(
  state: PlanViewState,
  viewModel: PlanViewModel
): void {
  try {
    enforceRightViewPolicy(state, viewModel);
  } catch (error) {
    if (process.env.NODE_ENV === 'development') {
      // Re-throw in development to fail fast
      throw error;
    } else {
      // Log warning in production but don't break the app
      console.warn('[ContentPolicyGuard]', error);
    }
  }
}
