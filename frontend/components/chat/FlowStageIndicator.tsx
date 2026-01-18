// frontend/components/chat/FlowStageIndicator.tsx
'use client';

import { Check, Eye,Loader2, MapPin, Sparkles } from 'lucide-react';
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
 * Stage configuration with labels and icons
 */
const STAGE_CONFIG: Record<
  TripPlanningStage,
  { label: string; shortLabel: string; step: number }
> = {
  greeting: { label: 'Welcome', shortLabel: 'Start', step: 1 },
  collecting: { label: 'Tell me about your trip', shortLabel: 'Details', step: 2 },
  ready: { label: 'Ready to plan', shortLabel: 'Ready', step: 3 },
  generating: { label: 'Creating your itinerary', shortLabel: 'Planning', step: 4 },
  viewing: { label: 'View your plan', shortLabel: 'View', step: 4 },
};

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
 * FlowStageIndicator - Shows user progress through the trip planning flow.
 *
 * A minimal progress indicator that helps first-time users understand
 * where they are in the planning process.
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

  const config = STAGE_CONFIG[stage];
  const totalSteps = 4;

  // Don't show on greeting stage (before first user message)
  // Don't show on viewing stage (branches are already visible, indicator is redundant)
  if (stage === 'greeting' || stage === 'viewing') return null;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground bg-muted/30 rounded-full border border-border/30">
      {/* Stage icon */}
      <StageIcon stage={stage} />

      {/* Stage label */}
      <span className="font-medium text-foreground/80">{config.shortLabel}</span>

      {/* Progress dots */}
      <div className="flex items-center gap-1 ml-1">
        {Array.from({ length: totalSteps }).map((_, i) => {
          const stepNum = i + 1;
          const isCompleted = stepNum < config.step;
          const isCurrent = stepNum === config.step;

          return (
            <div
              key={stepNum}
              className={`h-1.5 w-1.5 rounded-full transition-colors ${
                isCompleted
                  ? 'bg-primary'
                  : isCurrent
                    ? 'bg-primary/60 animate-pulse'
                    : 'bg-border'
              }`}
            />
          );
        })}
      </div>

      {/* Missing field hint (for collecting stage) */}
      {stage === 'collecting' && displayMissingFields.length > 0 && (
        <span className="text-muted-foreground/70 ml-1">
          • need {displayMissingFields.join(', ')}
        </span>
      )}

      {/* Ready indicator */}
      {stage === 'ready' && (
        <span className="text-primary ml-1">• ready to generate!</span>
      )}
    </div>
  );
}

/**
 * StageIcon - Renders the appropriate icon for each stage
 */
function StageIcon({ stage }: { stage: TripPlanningStage }) {
  const iconClass = 'h-3.5 w-3.5';

  switch (stage) {
    case 'greeting':
      return <MapPin className={iconClass} />;
    case 'collecting':
      return <MapPin className={iconClass} />;
    case 'ready':
      return <Check className={`${iconClass} text-primary`} />;
    case 'generating':
      return <Loader2 className={`${iconClass} animate-spin text-primary`} />;
    case 'viewing':
      return <Eye className={iconClass} />;
    default:
      return <Sparkles className={iconClass} />;
  }
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
