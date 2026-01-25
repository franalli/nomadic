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
  Building,
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
import type { Tile } from '@/types/tile';

import { TripHealthBar } from '../TripHealthBar';

// Topic priority for stable ordering
const TOPIC_PRIORITY = ['skiing', 'hiking', 'diving', 'boating', 'cycling', 'local_expert', 'general'];

// Topic configuration with icons and labels
const TOPIC_CONFIG: Record<string, {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  // Default action log for demo visibility
  readyAction: string;
  updatingAction: string;
}> = {
  hiking: {
    icon: Mountain,
    label: 'Hiking',
    readyAction: 'Verified trail conditions and permits',
    updatingAction: 'Checking seasonal trail access...',
  },
  diving: {
    icon: Waves,
    label: 'Diving',
    readyAction: 'Confirmed dive sites and safety intervals',
    updatingAction: 'Checking dive site availability...',
  },
  skiing: {
    icon: Snowflake,
    label: 'Skiing',
    readyAction: 'Verified resort conditions and lift passes',
    updatingAction: 'Checking snow conditions...',
  },
  boating: {
    icon: Sailboat,
    label: 'Boating',
    readyAction: 'Confirmed marina availability and weather',
    updatingAction: 'Checking marina schedules...',
  },
  cycling: {
    icon: Bike,
    label: 'Cycling',
    readyAction: 'Mapped routes and elevation profiles',
    updatingAction: 'Analyzing route conditions...',
  },
  local_expert: {
    icon: Building,
    label: 'Local Expert',
    readyAction: 'Verified local logistics and booking requirements',
    updatingAction: 'Checking city constraints...',
  },
  general: {
    icon: Sparkles,
    label: 'General',
    readyAction: 'Optimized itinerary and logistics',
    updatingAction: 'Planning logistics...',
  },
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
  /** Tiles for TripHealthBar inventory counts */
  tiles?: Record<string, Tile>;
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

  // Feasibility state from Constraint Engine
  const isInfeasible = section.feasibility_status === 'infeasible';
  const hasCaveat = section.feasibility_status === 'caveat';

  return (
    // 1. data-topic attribute for CSS color system
    // 2. Left accent border (3px, strong color)
    // 3. Infeasible/caveat border colors
    <div
      data-topic={topic}
      className={cn(
        "bg-card rounded-lg border overflow-hidden shadow-sm topic-border-left",
        isInfeasible && "border-red-500/50 bg-red-950/10",
        hasCaveat && "border-amber-500/30",
        !isInfeasible && !hasCaveat && "border-border"
      )}
    >
      {/* 3. Header with subtle tint */}
      <button
        onClick={onToggle}
        className={cn(
          "w-full px-4 py-3 text-left transition-colors",
          isInfeasible ? "bg-red-950/20 hover:bg-red-950/30" : "topic-header-tint hover:bg-muted/30"
        )}
      >
        {/* Row 1: Specialist badge + Status chip + Plan/Booking badges */}
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2">
            {/* Topic badge with icon (strong color, or red if infeasible) */}
            <span className={cn(
              "inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium",
              isInfeasible ? "bg-red-500/20 text-red-400" : "topic-badge"
            )}>
              <Icon className="w-3 h-3" />
              {config.label} Specialist
            </span>

            {/* Infeasible badge */}
            {isInfeasible && (
              <span className="text-[10px] px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded font-medium uppercase tracking-wider">
                Unavailable
              </span>
            )}

            {/* Caveat badge */}
            {hasCaveat && (
              <span className="text-[10px] px-1.5 py-0.5 bg-amber-500/20 text-amber-400 rounded font-medium">
                Limited
              </span>
            )}

            {/* Status chip - only show if NOT infeasible */}
            {!isInfeasible && (
              <span className={cn(
                "text-[10px] px-1.5 py-0.5 rounded font-medium",
                status === 'ready' && "bg-green-500/10 text-green-600 dark:text-green-400",
                status === 'updating' && "bg-amber-500/10 text-amber-600 dark:text-amber-400 animate-pulse",
                status === 'needs_input' && "bg-muted text-muted-foreground"
              )}>
                {status === 'ready' ? 'Ready' : status === 'updating' ? 'Updating...' : 'Needs input'}
              </span>
            )}
          </div>
          {/* Plan + Booking mini-badges - hide if infeasible */}
          {!isInfeasible && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] px-1.5 py-0.5 bg-muted rounded">Plan</span>
              <span className="text-[10px] px-1.5 py-0.5 bg-muted rounded">Booking</span>
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="w-4 h-4 text-muted-foreground" />
              )}
            </div>
          )}
        </div>

        {/* Infeasible reason message */}
        {isInfeasible && section.feasibility_reason && (
          <div className="mt-2 text-xs text-red-400">
            {section.feasibility_reason}
          </div>
        )}

        {/* Alternative suggestion for infeasible */}
        {isInfeasible && section.alternative_suggestion && (
          <div className="mt-1 text-[10px] text-muted-foreground">
            💡 {section.alternative_suggestion}
          </div>
        )}

        {/* Caveat warning message */}
        {hasCaveat && section.feasibility_reason && (
          <div className="mt-2 text-xs text-amber-400 flex items-center gap-1">
            <span>⚠️</span>
            <span>{section.feasibility_reason}</span>
          </div>
        )}

        {/* Mini-log: Last action performed by this specialist (not for infeasible) */}
        {!isInfeasible && status !== 'needs_input' && (
          <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span className={cn(
              status === 'ready' ? 'text-green-600 dark:text-green-400' : 'text-amber-600 dark:text-amber-400'
            )}>
              {status === 'ready' ? '✓' : '○'}
            </span>
            <span className="font-mono">
              {status === 'ready' ? config.readyAction : config.updatingAction}
            </span>
          </div>
        )}

        {/* Row 2 (collapsed): One-liner + principle chips (not for infeasible) */}
        {!isExpanded && !isInfeasible && (
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

      {/* Expanded content (normal bg-card, no tint) - NOT shown for infeasible */}
      {isExpanded && !isInfeasible && (
        <div className="px-4 pb-4 pt-2 border-t border-border/50 space-y-4">
          {/* Trip Summary (General Agent only) */}
          {section.trip_summary && (
            <div className="font-mono text-xs space-y-1 py-2 border-b border-border/30">
              <div>
                <span className="text-muted-foreground">Trip:</span>{' '}
                <span className="text-card-foreground">{section.trip_summary.destination}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Dates:</span>{' '}
                <span className="text-card-foreground">{section.trip_summary.dates}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Travelers:</span>{' '}
                <span className="text-card-foreground">{section.trip_summary.travelers}</span>
              </div>
            </div>
          )}

          {/* Constraints Applied (specialist agents) */}
          {section.constraints_applied && section.constraints_applied.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Constraints Applied
              </h5>
              <ul className="space-y-1.5">
                {section.constraints_applied.map((c, idx) => (
                  <li
                    key={idx}
                    className="text-xs font-mono flex items-start gap-2"
                  >
                    <span className="text-green-500 dark:text-green-400 mt-0.5">✓</span>
                    <span className="text-card-foreground">{c.rule}</span>
                    <span className="text-muted-foreground">({c.type})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Content Added (specialist agents) */}
          {section.content_added && section.content_added.length > 0 && (
            <div>
              <h5 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Content Added
              </h5>
              <ul className="space-y-1.5">
                {section.content_added.map((c, idx) => (
                  <li
                    key={idx}
                    className="text-xs flex items-start gap-2"
                  >
                    <span className="text-blue-500 dark:text-blue-400 mt-0.5">+</span>
                    <span className="text-card-foreground">{c.title}</span>
                    {c.day && (
                      <span className="text-muted-foreground">(Day {c.day})</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

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
  /** Tiles for TripHealthBar inventory counts */
  tiles?: Record<string, Tile>;
}

function StrategyStack({
  sections,
  pendingTopics,
  executedTopics,
  tiles = {},
}: StrategyStackProps) {
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

  // Extract General agent separately for TripHealthDashboard
  const generalSection = sections.find((s) => s.specialist_type === 'general');
  // Filter out General from card list (it gets TripHealthDashboard instead)
  const filtered = sections.filter((s) => s.specialist_type !== 'general');
  // Always show TripHealthDashboard when General agent exists (replaces General AgentCard)
  // This provides consistent UX whether specialists are active or not
  const showTripHealth = generalSection && Object.keys(tiles).length > 0;

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

  // Header semantics: Specialist Logic (N) when specialists exist
  const hasExecuted = executedTopics.length > 0;
  const hasPending = pendingTopics.length > 0;
  // Count only non-general specialists for the feed
  const specialistCount = sorted.length;

  // Count specialists (excluding general)
  const executedSpecialistCount = executedTopics.filter(t => t !== 'general').length;

  // Header text: Only show when specialists exist or are pending
  // Don't show "Specialists (0)" - that's confusing when only General ran
  const headerText = specialistCount > 0
    ? `Specialist Logic (${specialistCount})`
    : hasPending
      ? 'Specialist Logic'
      : executedSpecialistCount > 0
        ? `Specialists (${executedSpecialistCount})`
        : '';  // Empty = hide header entirely

  // Should we show the specialist header? Only if there are specialists or pending
  const showSpecialistHeader = headerText || hasPending;

  return (
    <div className="space-y-2" data-reduced-color={useReducedColor}>
      {/* Specialist header - only show when specialists exist or are pending */}
      {showSpecialistHeader && (
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
            {/* Topic badges - only show specialist topics (General is in TripHealthBar) */}
            {executedSpecialistCount > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-1">
                {executedTopics.filter(t => t !== 'general').map(topic => {
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
      )}

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
                {config.label} Specialist
              </span>
              <span className="text-[10px] px-1.5 py-0.5 bg-amber-500/10 text-amber-600 dark:text-amber-400 rounded font-medium animate-pulse">
                Updating...
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-2">Generating strategy...</p>
          </div>
        );
      })}

      {/* Trip Health Bar (compact status bar from General agent - always at top) */}
      {showTripHealth && (
        <TripHealthBar
          tripSummary={generalSection?.trip_summary}
          tiles={tiles}
        />
      )}

      {/* Stacked specialist cards */}
      {visible.length > 0 ? (
        visible.map((section) => {
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
        })
      ) : (
        /* Clean state: No specialists yet, show subtle hint */
        !hasPending && showTripHealth && (
          <div className="text-center py-6 opacity-40">
            <p className="text-xs font-mono uppercase tracking-widest">System Ready</p>
            <p className="text-[10px] text-muted-foreground mt-1">
              Add activities like diving or hiking to see specialist logic
            </p>
          </div>
        )
      )}

      {/* Overflow expander */}
      {overflow > 0 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="text-xs text-primary hover:underline py-1"
        >
          +{overflow} more specialist{overflow > 1 ? 's' : ''}
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
  tiles = {},
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
      {/* Strategy stack - TripHealthBar (General) + Specialist cards */}
      <StrategyStack
        sections={strategy_sections}
        pendingTopics={pendingTopics}
        executedTopics={resolvedExecutedTopics}
        tiles={tiles}
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
