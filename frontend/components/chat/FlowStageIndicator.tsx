// frontend/components/chat/FlowStageIndicator.tsx
'use client';

import { Loader2 } from 'lucide-react';
import { useMemo } from 'react';

/**
 * Flow stages for trip planning
 */
export type TripPlanningStage =
  | 'greeting' // Initial welcome
  | 'collecting' // Gathering trip details
  | 'ready' // All fields collected
  | 'generating' // Creating itinerary
  | 'viewing'; // Browsing branches

interface FlowStageIndicatorProps {
  /** Current stage of the planning flow */
  stage: TripPlanningStage;
  /** Missing fields for the 'collecting' stage */
  missingFields?: string[];
  /** Whether to show the indicator (hidden on first message) */
  visible?: boolean;
}

/**
 * Human-readable field names
 */
const FIELD_LABELS: Record<string, string> = {
  destinations: 'destination',
  origin: 'origin',
  dates: 'dates',
  start_date: 'dates',
  end_date: 'dates',
  adults: 'travelers',
  travelers: 'travelers',
  budget: 'budget',
};

/**
 * FlowStageIndicator - Shows current plan state as a simple status indicator.
 *
 * YC-aligned: reads as status, not journey. No wizard dots, no sequence.
 * Format: "Plan state · Awaiting dates" or "Plan state · Ready to plan"
 */
export function FlowStageIndicator({
  stage,
  missingFields = [],
  visible = true,
}: FlowStageIndicatorProps) {
  // Derive displayable missing fields
  const displayMissingFields = useMemo(() => {
    // Deduplicate and convert to human-readable labels
    const labels = new Set<string>();
    for (const field of missingFields) {
      const label = FIELD_LABELS[field] || field;
      labels.add(label);
    }
    return Array.from(labels).slice(0, 2); // Show at most 2
  }, [missingFields]);

  if (!visible) return null;

  // Don't show on greeting stage (before first user message)
  // Don't show on viewing stage (branches are already visible, indicator is redundant)
  if (stage === 'greeting' || stage === 'viewing') return null;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-muted/20 rounded-lg border border-border/20">
      <span className="font-medium text-foreground/60 tracking-wide">Plan state</span>
      <span className="text-border">·</span>

      {stage === 'collecting' && displayMissingFields.length > 0 ? (
        <span className="text-muted-foreground">Awaiting {displayMissingFields.join(', ')}</span>
      ) : stage === 'ready' ? (
        <span className="text-primary/80">Ready to plan</span>
      ) : stage === 'generating' ? (
        <span className="text-primary/80 flex items-center gap-1.5">
          <Loader2 className="h-3 w-3 animate-spin" />
          Planning
        </span>
      ) : (
        <span className="text-muted-foreground">Collecting details</span>
      )}
    </div>
  );
}

/**
 * Helper to determine the current stage from props
 */
export function determineStage({
  hasUserMessage,
  readyToGenerate,
  isGenerating,
  hasBranches,
  missingFields,
}: {
  hasUserMessage: boolean;
  readyToGenerate?: boolean;
  isGenerating?: boolean;
  hasBranches?: boolean;
  missingFields?: string[];
}): TripPlanningStage {
  if (!hasUserMessage) return 'greeting';
  if (isGenerating) return 'generating';
  if (hasBranches) return 'viewing';
  if (readyToGenerate) return 'ready';
  if (missingFields && missingFields.length > 0) return 'collecting';
  return 'collecting'; // Default to collecting if unsure
}
