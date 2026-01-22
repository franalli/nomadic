/**
 * S0BootstrapView
 *
 * Bootstrap state view - shows NextStepPanel with truthful checklist.
 * Uses "Finish setup" panel instead of misleading "Strategy/Itinerary" scaffold.
 *
 * Content rules:
 * - Shows actual requirements: Destination, Start date
 * - Optional: Trip length (needed to price stays + build itinerary)
 * - Defaulted: Travelers (1 adult)
 * - Optional: Budget
 * - Conditional: Origin (only when Flights ON)
 * - No "Strategy" wording in setup phase
 * - "Build plan" CTA disabled until required fields met
 *
 * NOTE: NextStepPanel reads from document store directly (single source of truth)
 * so we only pass action handlers and generation state.
 */

'use client';

import { NextStepPanel } from '@/components/planner/NextStepPanel';

interface S0BootstrapViewProps {
  /** Generation state */
  isGenerating?: boolean;
  generatingSubtitle?: string;
  /** Actions - open corresponding sheets */
  onBuildPlan?: () => void;
  onSetDestination?: () => void;
  onSetOrigin?: () => void;
  onSetDates?: () => void;
  onSetTravelers?: () => void;
  onSetBudget?: () => void;
}

export function S0BootstrapView({
  isGenerating,
  generatingSubtitle,
  onBuildPlan,
  onSetDestination,
  onSetOrigin,
  onSetDates,
  onSetTravelers,
  onSetBudget,
}: S0BootstrapViewProps) {
  return (
    <NextStepPanel
      isGenerating={isGenerating}
      generatingSubtitle={generatingSubtitle}
      onBuildPlan={onBuildPlan}
      onSetDestination={onSetDestination}
      onSetOrigin={onSetOrigin}
      onSetDates={onSetDates}
      onSetTravelers={onSetTravelers}
      onSetBudget={onSetBudget}
    />
  );
}

export default S0BootstrapView;
