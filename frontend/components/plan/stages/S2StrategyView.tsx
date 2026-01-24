/**
 * S2StrategyView
 *
 * Strategy ready state - shows stacked strategy cards (one per topic) and open decisions.
 * This is the main planning view before itinerary generation.
 *
 * NOTE: This component renders CONTENT ONLY.
 * Header and CTAs are owned by StrategyStageRenderer.
 */

'use client';

import { AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';
import React from 'react';

import type {
  DestinationCard,
  OpenDecision,
  PlanViewModel,
  StrategySection,
} from '@/types/plan-envelope';

// Topic priority for stable ordering
const TOPIC_PRIORITY = ['skiing', 'hiking', 'diving', 'boating', 'cycling', 'general'];

interface S2StrategyViewProps {
  viewModel: PlanViewModel;
  /** @deprecated Header is now rendered by StrategyStageRenderer */
  destinationCard?: DestinationCard;
  onRefineAssumptions?: () => void;
  /** @deprecated CTA is now rendered by NextStepBar */
  canExpandToItinerary?: boolean;
}

// =============================================================================
// TopicCard - Single strategy topic with collapse/expand
// =============================================================================

interface TopicCardProps {
  section: StrategySection;
  isExpanded: boolean;
  onToggle: () => void;
}

function TopicCard({ section, isExpanded, onToggle }: TopicCardProps) {
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

  const topicLabel = section.specialist_type
    ? section.specialist_type.charAt(0).toUpperCase() +
      section.specialist_type.slice(1)
    : 'General';

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden shadow-sm">
      {/* Header - topic badge + one-liner (collapsed) or just badge (expanded) */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex flex-col items-start text-left hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center justify-between w-full">
          <span className="text-xs px-2 py-0.5 bg-primary/10 text-primary rounded-full font-medium">
            {topicLabel}
          </span>
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="w-4 h-4 text-muted-foreground" />
          )}
        </div>

        {/* Collapsed: one-liner + principles chips */}
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

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-2 border-t border-border/50 space-y-4">
          {/* Must-dos */}
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
                    <span className="text-primary mt-0.5">•</span>
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
        </div>
      )}
    </div>
  );
}

// =============================================================================
// StrategyStack - Stacked strategy cards with overflow handling
// =============================================================================

interface StrategyStackProps {
  sections: StrategySection[];
}

function StrategyStack({ sections }: StrategyStackProps) {
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

  return (
    <div className="space-y-2">
      {/* Multi-topic indicator (desktop only) */}
      {sorted.length > 1 && !isMobile && (
        <p className="text-xs text-muted-foreground">
          {sorted.length} specialist{sorted.length > 1 ? ' strategies' : ' strategy'} generated
        </p>
      )}

      {/* Stacked cards */}
      {visible.map((section) => (
        <TopicCard
          key={section.id}
          section={section}
          isExpanded={expandedId === section.id}
          onToggle={() =>
            setExpandedId(expandedId === section.id ? null : section.id)
          }
        />
      ))}

      {/* Overflow expander */}
      {overflow > 0 && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="text-xs text-primary hover:underline py-1"
        >
          +{overflow} more strategy topic{overflow > 1 ? 's' : ''}
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
}: S2StrategyViewProps) {
  // Unused props - header and CTA now owned by StrategyStageRenderer
  void _destinationCard;
  void _canExpandToItinerary;

  const { strategy_sections = [], open_decisions = [] } = viewModel;

  // Skeleton state - show when strategy is being prepared (empty sections)
  if (strategy_sections.length === 0) {
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
      <StrategyStack sections={strategy_sections} />

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
