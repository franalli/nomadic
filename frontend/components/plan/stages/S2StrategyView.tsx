/**
 * S2StrategyView
 *
 * Strategy ready state - shows stacked agent cards (one per topic) with color-coded UI.
 * This is the main planning view before itinerary generation.
 *
 * NOTE: This component renders CONTENT ONLY.
 * Header and CTAs are owned by StrategyStageRenderer.
 *
 * Agent status is COMPUTED from pending/executed topics, not stored on section.
 */

'use client';

import {
  AlertCircle,
  Bike,
  ChevronDown,
  ChevronRight,
  Mountain,
  Sailboat,
  Snowflake,
  Sparkles,
  Waves,
} from 'lucide-react';
import React from 'react';

import { cn } from '@/lib/utils';
import {
  type AgentStatus,
  computeAgentStatus,
  type DestinationCard,
  type OpenDecision,
  type PlanViewModel,
  type StrategySection,
} from '@/types/plan-envelope';

// Topic priority for stable ordering
const TOPIC_PRIORITY = ['skiing', 'hiking', 'diving', 'boating', 'cycling', 'general'];

// Topic configuration with icons and labels
const TOPIC_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}> = {
  hiking: { icon: Mountain, label: 'Hiking' },
  diving: { icon: Waves, label: 'Diving' },
  skiing: { icon: Snowflake, label: 'Skiing' },
  boating: { icon: Sailboat, label: 'Boating' },
  cycling: { icon: Bike, label: 'Cycling' },
  general: { icon: Sparkles, label: 'General' },
};

interface S2StrategyViewProps {
  viewModel: PlanViewModel;
  /** @deprecated Header is now rendered by StrategyStageRenderer */
  destinationCard?: DestinationCard;
  onRefineAssumptions?: () => void;
  /** @deprecated CTA is now rendered by NextStepBar */
  canExpandToItinerary?: boolean;
  /** Topics pending execution (for "Updating..." state) */
  pendingTopics?: string[];
  /** Topics that have been executed (from viewModel.executed_strategy_topics) */
  executedTopics?: string[];
}

// =============================================================================
// AgentCard - Single agent card with topic color system
// =============================================================================

interface AgentCardProps {
  section: StrategySection;
  isExpanded: boolean;
  onToggle: () => void;
  status: AgentStatus;
}

function AgentCard({ section, isExpanded, onToggle, status }: AgentCardProps) {
  // Fallback logic for backward compatibility with legacy responses
  const oneLiner = section.one_liner || section.bullets[0] || '';
  const principles =
    section.principles && section.principles.length > 0
      ? section.principles
      : section.bullets.slice(0, 3);
  const mustDos =
    section.must_dos && section.must_dos.length > 0
      ? section.must_dos
      : section.bullets;

  const topic = section.specialist_type || 'general';
  const config = TOPIC_CONFIG[topic] || TOPIC_CONFIG.general;
  const Icon = config.icon;

  return (
    // 1. data-topic attribute for CSS color system
    // 2. Left accent border (3px, strong color)
    <div
      data-topic={topic}
      className="bg-card rounded-lg border border-border overflow-hidden shadow-sm topic-border-left"
    >
      {/* 3. Header with subtle tint */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 text-left topic-header-tint hover:bg-muted/30 transition-colors"
      >
        {/* Row 1: Agent badge + Status chip + Plan/Booking badges */}
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            {/* Topic badge with icon (strong color) */}
            <span className="topic-badge inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium">
              <Icon className="w-3 h-3" />
              {config.label} Agent
            </span>
            {/* Status chip - COMPUTED */}
            <span className={cn(
              "text-[10px] px-1.5 py-0.5 rounded font-medium",
              status === 'ready' && "bg-green-500/10 text-green-600 dark:text-green-400",
              status === 'updating' && "bg-amber-500/10 text-amber-600 dark:text-amber-400 animate-pulse",
              status === 'needs_input' && "bg-muted text-muted-foreground"
            )}>
              {status === 'ready' ? 'Ready' : status === 'updating' ? 'Updating...' : 'Needs input'}
            </span>
          </div>
          {/* Plan + Booking mini-badges */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] px-1.5 py-0.5 bg-muted rounded">Plan</span>
            <span className="text-[10px] px-1.5 py-0.5 bg-muted rounded">Booking</span>
            {isExpanded ? (
              <ChevronDown className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            )}
          </div>
        </div>

        {/* Row 2 (collapsed): One-liner + principle chips */}
        {!isExpanded && (
          <div className="mt-2 w-full">
            {oneLiner && (
              <p className="text-xs text-muted-foreground mb-2">{oneLiner}</p>
            )}
            {principles.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {principles.slice(0, 4).map((p, i) => (
                  <span
                    key={i}
                    className="text-xs px-2 py-0.5 bg-muted rounded-full"
                  >
                    {p}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </button>

      {/* Expanded content (normal bg-card, no tint) */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-2 border-t border-border/50 space-y-4">
          {/* Booking artifacts row */}
          {section.booking_artifacts && (
            <div className="flex flex-wrap gap-2 py-2 border-b border-border/30">
              <span className="text-xs text-muted-foreground">Booking surfaces:</span>
              {section.booking_artifacts.activities_count > 0 && (
                <span className="text-xs topic-bullet font-medium">
                  {section.booking_artifacts.activities_count} activities shortlisted
                </span>
              )}
              {section.booking_artifacts.hotels_count > 0 && (
                <span className="text-xs topic-bullet font-medium">
                  {section.booking_artifacts.hotels_count} hotels recommended
                </span>
              )}
            </div>
          )}

          {/* Must-dos with topic-colored bullets */}
          {mustDos.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Must-dos
              </h5>
              <ul className="space-y-1.5">
                {mustDos.slice(0, 5).map((item, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-card-foreground flex items-start gap-2"
                  >
                    <span className="topic-bullet mt-0.5">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Optional upgrades */}
          {section.optional_upgrades && section.optional_upgrades.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Optional upgrades
              </h5>
              <ul className="space-y-1.5">
                {section.optional_upgrades.slice(0, 3).map((item, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-muted-foreground flex items-start gap-2"
                  >
                    <span className="text-muted-foreground/70 mt-0.5">+</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Logistics notes */}
          {section.logistics_notes && section.logistics_notes.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Logistics
              </h5>
              <ul className="space-y-1.5">
                {section.logistics_notes.slice(0, 4).map((item, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-muted-foreground flex items-start gap-2"
                  >
                    <span className="text-muted-foreground/50 mt-0.5">-</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Tradeoffs summary */}
          {section.tradeoffs_summary && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Why this approach
              </h5>
              <p className="text-xs text-muted-foreground">
                {section.tradeoffs_summary}
              </p>
            </div>
          )}

          {/* Impact areas */}
          {section.impact_areas && section.impact_areas.length > 0 && (
            <div className="flex items-center gap-2 pt-2 border-t border-border/30">
              <span className="text-xs text-muted-foreground">Impact:</span>
              {section.impact_areas.map((area, i) => (
                <span key={i} className="text-xs px-1.5 py-0.5 topic-badge rounded">
                  {area}
                </span>
              ))}
            </div>
          )}

          {/* Provenance (debug info) */}
          {(section.strategy_node_id || section.strategy_version) && (
            <details className="text-[10px] text-muted-foreground/70">
              <summary className="cursor-pointer">ⓘ Provenance</summary>
              <p className="mt-1 pl-2">
                Generated by: <span className="topic-bullet">{section.strategy_node_id}</span>
                {section.strategy_version && ` • v${section.strategy_version}`}
              </p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// StrategyStack - Stacked agent cards with overflow handling
// =============================================================================

interface StrategyStackProps {
  sections: StrategySection[];
  pendingTopics: string[];
  executedTopics: string[];
}

function StrategyStack({ sections, pendingTopics, executedTopics }: StrategyStackProps) {
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [showAll, setShowAll] = React.useState(false);

  // Simple responsive check (can use proper hook if available)
  const [isMobile, setIsMobile] = React.useState(false);
  React.useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 1024);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // Filter out General when specialists exist
  const hasSpecialists = sections.some(
    (s) => s.specialist_type && s.specialist_type !== 'general'
  );
  const filtered = hasSpecialists
    ? sections.filter((s) => s.specialist_type !== 'general')
    : sections;

  // Sort by topic priority for stable ordering
  const sorted = [...filtered].sort((a, b) => {
    const aIdx = TOPIC_PRIORITY.indexOf(a.specialist_type || 'general');
    const bIdx = TOPIC_PRIORITY.indexOf(b.specialist_type || 'general');
    return aIdx - bIdx;
  });

  // Apply visible limit
  const visibleLimit = isMobile ? 1 : 2;
  const visible = showAll ? sorted : sorted.slice(0, visibleLimit);
  const overflow = sorted.length - visibleLimit;

  // Reduced color mode for 3+ agents
  const useReducedColor = sorted.length > 2;

  // Header semantics: don't mislabel pending as executed, never show "0" while cards visible
  const hasExecuted = executedTopics.length > 0;
  const hasPending = pendingTopics.length > 0;
  const totalVisible = executedTopics.length + pendingTopics.length + sorted.length;

  // Header text: "Agents executed (N)" if executed, else "Agents (N)" to avoid "executed (0)"
  const headerText = hasExecuted
    ? `Agents executed (${executedTopics.length})`
    : totalVisible > 0
      ? `Agents (${totalVisible})`
      : 'Agents';

  return (
    <div className="space-y-2" data-reduced-color={useReducedColor}>
      {/* Agents header with color-coded topic badges */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-medium text-card-foreground flex items-center gap-2">
            {headerText}
            {/* Updating indicator when pending topics exist */}
            {hasPending && (
              <span className="text-xs px-1.5 py-0.5 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded font-medium animate-pulse">
                Updating ({pendingTopics.length})
              </span>
            )}
          </h3>
          {/* Topic badges - only show executed topics here (truthful) */}
          {hasExecuted && (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {executedTopics.map(topic => {
                const config = TOPIC_CONFIG[topic] || TOPIC_CONFIG.general;
                const TopicIcon = config.icon;
                return (
                  <span
                    key={topic}
                    data-topic={topic}
                    className="topic-badge inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full"
                  >
                    <TopicIcon className="w-2.5 h-2.5" />
                    {config.label}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Pending topics placeholder (updating state) */}
      {pendingTopics.map(topic => {
        const config = TOPIC_CONFIG[topic] || TOPIC_CONFIG.general;
        const TopicIcon = config.icon;
        return (
          <div
            key={`pending-${topic}`}
            data-topic={topic}
            className="bg-card rounded-lg border border-border px-4 py-3 topic-border-left"
          >
            <div className="flex items-center gap-2">
              <span className="topic-badge inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium">
                <TopicIcon className="w-3 h-3" />
                {config.label} Agent
              </span>
              <span className="text-[10px] px-1.5 py-0.5 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded font-medium animate-pulse">
                Updating...
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Generating strategy...</p>
          </div>
        );
      })}

      {/* Stacked agent cards */}
      {visible.map((section) => {
        const topic = section.specialist_type || 'general';
        const status = computeAgentStatus(topic, pendingTopics, executedTopics);
        return (
          <AgentCard
            key={section.id}
            section={section}
            isExpanded={expandedId === section.id}
            onToggle={() =>
              setExpandedId(expandedId === section.id ? null : section.id)
            }
            status={status}
          />
        );
      })}

      {/* Overflow expander */}
      {overflow > 0 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="text-xs text-primary hover:underline py-1"
        >
          +{overflow} more agent{overflow > 1 ? 's' : ''}
        </button>
      )}
    </div>
  );
}

// =============================================================================
// OpenDecisionsPanel - Blocking/non-blocking decisions
// =============================================================================

function OpenDecisionsPanel({ decisions }: { decisions: OpenDecision[] }) {
  if (decisions.length === 0) return null;

  const blockingCount = decisions.filter((d) => d.is_blocking).length;

  return (
    <div className="bg-amber-500/10 rounded-lg border border-amber-500/30 p-4 dark:bg-amber-900/20 dark:border-amber-700/30">
      <div className="flex items-center gap-2 mb-3">
        <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-500" />
        <h3 className="text-sm font-medium text-amber-900 dark:text-amber-200">
          Open decisions
          {blockingCount > 0 && (
            <span className="text-amber-700 dark:text-amber-400 ml-1">
              ({blockingCount} blocking)
            </span>
          )}
        </h3>
      </div>
      <ul className="space-y-2">
        {decisions.slice(0, 4).map((decision) => (
          <li key={decision.id} className="flex items-start gap-2">
            <span
              className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                decision.is_blocking ? 'bg-amber-500' : 'bg-muted-foreground/50'
              }`}
            />
            <span className="text-xs text-card-foreground">
              {decision.statement}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// =============================================================================
// S2StrategyView - Main export
// =============================================================================

export function S2StrategyView({
  viewModel,
  destinationCard: _destinationCard,
  onRefineAssumptions,
  canExpandToItinerary: _canExpandToItinerary,
  pendingTopics = [],
  executedTopics,
}: S2StrategyViewProps) {
  // Unused props - header and CTA now owned by StrategyStageRenderer
  void _destinationCard;
  void _canExpandToItinerary;

  const { strategy_sections = [], open_decisions = [] } = viewModel;

  // Use viewModel's executed_strategy_topics if not provided via props
  const resolvedExecutedTopics = executedTopics ?? viewModel.executed_strategy_topics ?? [];

  // Skeleton state - show when strategy is being prepared (empty sections)
  if (strategy_sections.length === 0 && pendingTopics.length === 0) {
    return (
      <div className="flex flex-col p-4 space-y-4">
        <div className="bg-card rounded-lg border border-border px-4 py-3 shadow-sm">
          <p className="text-xs text-muted-foreground">
            Strategy is being prepared...
          </p>
        </div>
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="bg-card rounded-lg border border-border px-4 py-3 shadow-sm"
          >
            <div className="h-4 bg-muted rounded w-2/3 animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col p-4 space-y-4">
      {/* Strategy stack - one card per executed topic */}
      <StrategyStack
        sections={strategy_sections}
        pendingTopics={pendingTopics}
        executedTopics={resolvedExecutedTopics}
      />

      {/* Open decisions panel */}
      <OpenDecisionsPanel decisions={open_decisions} />

      {/* Secondary action - refine assumptions (optional) */}
      {onRefineAssumptions && (
        <button
          onClick={onRefineAssumptions}
          className="w-full py-2 px-4 rounded-lg text-sm text-muted-foreground hover:text-card-foreground hover:bg-muted transition-colors"
        >
          Refine assumptions
        </button>
      )}
    </div>
  );
}

export default S2StrategyView;
