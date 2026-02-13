/**
 * statusCopyMap.ts
 *
 * Centralized copy for the progress/status system.
 * Single source of truth for step labels, status messages, and sub-status text.
 */

const STATUS_COPY = {
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
export type StageKey = keyof typeof STATUS_COPY.stages;

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
