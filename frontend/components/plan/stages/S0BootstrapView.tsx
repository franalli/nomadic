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
 * Speculative Execution:
 * - Activates useSpeculativeExecution hook to preload specialist content
 * - Shows "Preview Insights" cards when specialist content is available
 * - Creates "Instant AI" feeling during Setup phase
 *
 * NOTE: NextStepPanel reads from document store directly (single source of truth)
 * so we only pass action handlers and generation state.
 */

'use client';

import {
  Bike,
  Building,
  Mountain,
  Sailboat,
  Snowflake,
  Waves,
} from 'lucide-react';
import React from 'react';

import { NextStepPanel } from '@/components/planner/NextStepPanel';
import { useSpeculativeExecution } from '@/hooks/useSpeculativeExecution';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

// Topic configuration with icons and labels (simplified from S2StrategyView)
const TOPIC_CONFIG: Record<
  string,
  {
    icon: React.ComponentType<{ className?: string }>;
    label: string;
  }
> = {
  hiking: { icon: Mountain, label: 'Hiking' },
  diving: { icon: Waves, label: 'Diving' },
  skiing: { icon: Snowflake, label: 'Skiing' },
  boating: { icon: Sailboat, label: 'Boating' },
  cycling: { icon: Bike, label: 'Cycling' },
  local_expert: { icon: Building, label: 'Local Expert' },
};

interface S0BootstrapViewProps {
  /** Generation state */
  isGenerating?: boolean;
  generatingSubtitle?: string;
  /** Whether user has ever had a plan generated (for CTA label) */
  hasEverHadPlan?: boolean;
  /** Actions - open corresponding sheets */
  onBuildPlan?: () => void;
  onSetDestination?: () => void;
  onSetOrigin?: () => void;
  onSetDates?: () => void;
  onSetTravelers?: () => void;
  onSetBudget?: () => void;
}

// =============================================================================
// SpecialistPreviewCard - Simplified agent card for Setup phase
// =============================================================================

interface SpecialistPreviewCardProps {
  section: StrategySection;
}

function SpecialistPreviewCard({ section }: SpecialistPreviewCardProps) {
  const topic = section.specialist_type || 'general';
  const config = TOPIC_CONFIG[topic];

  // Skip unknown topics or general
  if (!config || topic === 'general') return null;

  const Icon = config.icon;
  const oneLiner = section.one_liner || section.bullets[0] || '';

  // Feasibility state
  const isInfeasible = section.feasibility_status === 'infeasible';
  const hasCaveat = section.feasibility_status === 'caveat';

  return (
    <div
      data-topic={topic}
      className={cn(
        'bg-card rounded-lg border overflow-hidden shadow-sm topic-border-left',
        isInfeasible && 'border-red-500/50 bg-red-950/10',
        hasCaveat && 'border-amber-500/30',
        !isInfeasible && !hasCaveat && 'border-muted/60 bg-muted/5'
      )}
    >
      <div
        className={cn(
          'px-4 py-3',
          isInfeasible ? 'bg-red-950/20' : 'topic-header-tint'
        )}
      >
        {/* Header row: Badge + Status */}
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium',
              isInfeasible ? 'bg-red-500/20 text-red-400' : 'topic-badge'
            )}
          >
            <Icon className="w-3 h-3" />
            {config.label} Specialist
          </span>

          {isInfeasible && (
            <span className="text-[10px] px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded font-medium uppercase tracking-wider">
              Unavailable
            </span>
          )}

          {hasCaveat && (
            <span className="text-[10px] px-1.5 py-0.5 bg-amber-500/20 text-amber-400 rounded font-medium">
              Limited
            </span>
          )}

          {!isInfeasible && !hasCaveat && (
            <span className="text-[10px] px-1.5 py-0.5 bg-green-500/10 text-green-600 dark:text-green-400 rounded font-medium">
              Ready
            </span>
          )}
        </div>

        {/* Feasibility message */}
        {isInfeasible && section.feasibility_reason && (
          <p className="mt-2 text-xs text-red-400">
            {section.feasibility_reason}
          </p>
        )}

        {hasCaveat && section.feasibility_reason && (
          <p className="mt-2 text-xs text-amber-400 flex items-center gap-1">
            <span>⚠️</span>
            {section.feasibility_reason}
          </p>
        )}

        {/* One-liner summary (only when feasible) */}
        {!isInfeasible && oneLiner && (
          <p className="mt-2 text-xs text-muted-foreground">{oneLiner}</p>
        )}

        {/* Constraint preview chips */}
        {!isInfeasible &&
          section.constraints_applied &&
          section.constraints_applied.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {section.constraints_applied.slice(0, 2).map((c, i) => (
                <span
                  key={i}
                  className="text-[10px] px-1.5 py-0.5 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded"
                >
                  ✓ {c.rule.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          )}
      </div>
    </div>
  );
}

// =============================================================================
// S0BootstrapView - Main export
// =============================================================================

export function S0BootstrapView({
  isGenerating,
  generatingSubtitle,
  hasEverHadPlan,
  onBuildPlan,
  onSetDestination,
  onSetOrigin,
  onSetDates,
  onSetTravelers,
  onSetBudget,
}: S0BootstrapViewProps) {
  // Activate speculative execution hook
  useSpeculativeExecution();

  // Get specialist sections from document store
  const strategySections = useDocumentStore(
    (s) => s.document?.strategy_sections
  );
  const specialistSections = strategySections?.filter(
    (s) => s.specialist_type && s.specialist_type !== 'general'
  );

  return (
    <div className="flex flex-col gap-6">
      {/* Setup checklist panel */}
      <NextStepPanel
        isGenerating={isGenerating}
        generatingSubtitle={generatingSubtitle}
        hasEverHadPlan={hasEverHadPlan}
        onBuildPlan={onBuildPlan}
        onSetDestination={onSetDestination}
        onSetOrigin={onSetOrigin}
        onSetDates={onSetDates}
        onSetTravelers={onSetTravelers}
        onSetBudget={onSetBudget}
      />

      {/* Speculative Insights - Preview cards from preloaded specialist content */}
      {specialistSections && specialistSections.length > 0 && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <div className="flex items-center justify-between px-1">
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
              Preview Insights
            </h3>
            <span className="text-xs text-muted-foreground/60">
              Generated based on your interests
            </span>
          </div>

          <div className="space-y-3">
            {specialistSections.map((section) => (
              <SpecialistPreviewCard key={section.id} section={section} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default S0BootstrapView;
