/**
 * statusCopyMap.ts
 *
 * Centralized copy for the progress/status system.
 * Single source of truth for step labels, status messages, and sub-status text.
 */

export const STATUS_COPY = {
  // Header stepper labels
  steps: ['Setup', 'Plan', 'Book'] as const,

  // Status pill text (shown during generation)
  generating: 'Building plan…',
  expandingItinerary: 'Creating day-by-day…',

  // Sub-status by backend stage (small text below header)
  subStatus: {
    structure: 'Now: Drafting trip outline…',
    strategy: 'Now: Writing recommendations…',
    itinerary: 'Now: Creating day-by-day…',
    deals: 'Now: Finding deals…',
  } as const,

  // Internal stage display names (section headers if shown)
  stages: {
    structure: 'Outline',
    strategy: 'Recommendations',
    itinerary: 'Day-by-day',
  } as const,
} as const;

// Type helpers
export type StepName = (typeof STATUS_COPY.steps)[number];
export type SubStatusKey = keyof typeof STATUS_COPY.subStatus;
export type StageKey = keyof typeof STATUS_COPY.stages;

/**
 * Get the current step index (0-2) based on PlanViewState
 */
export function getStepIndex(
  planViewState: string,
  hasDestination: boolean,
  hasDates: boolean
): number {
  // S0 = Setup (0)
  if (planViewState === 'S0_BOOTSTRAP') {
    return 0;
  }

  // S1 = still in Setup if generating, otherwise Plan
  if (planViewState === 'S1_FRAMING') {
    return hasDestination && hasDates ? 1 : 0;
  }

  // S2 = Plan (1)
  if (planViewState.startsWith('S2_')) {
    return 1;
  }

  // S3 = Book (2)
  if (planViewState.startsWith('S3_')) {
    return 2;
  }

  return 0;
}

/**
 * Get completed steps based on current state
 */
export function getCompletedSteps(
  planViewState: string,
  hasDestination: boolean,
  hasDates: boolean
): boolean[] {
  // Setup is complete when we have destination + dates
  const setupComplete = hasDestination && hasDates;

  // Plan is complete when in S2_STRATEGY_READY or S3
  const planComplete =
    planViewState === 'S2_STRATEGY_READY' || planViewState.startsWith('S3_');

  // Book is complete when in S3_ITINERARY_READY
  const bookComplete = planViewState === 'S3_ITINERARY_READY';

  return [setupComplete, planComplete, bookComplete];
}

/**
 * Get the status pill text based on generation state
 */
export function getStatusPillText(
  isGenerating: boolean,
  isExpandingItinerary: boolean
): string | null {
  if (isExpandingItinerary) {
    return STATUS_COPY.expandingItinerary;
  }
  if (isGenerating) {
    return STATUS_COPY.generating;
  }
  return null;
}

/**
 * Get sub-status text based on current backend stage
 */
export function getSubStatusText(
  currentStage: string | null | undefined
): string | null {
  if (!currentStage) return null;

  const key = currentStage.toLowerCase() as SubStatusKey;
  return STATUS_COPY.subStatus[key] || null;
}
