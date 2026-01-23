/**
 * S2StrategyView
 *
 * Strategy ready state - shows strategy sections (collapsed) and open decisions.
 * This is the main planning view before itinerary generation.
 *
 * NOTE: This component renders CONTENT ONLY.
 * Header and CTAs are owned by StrategyStageRenderer.
 */

'use client';

import { AlertCircle,ChevronDown, ChevronRight } from 'lucide-react';
import React from 'react';

import type { DestinationCard, OpenDecision,PlanViewModel, StrategySection } from '@/types/plan-envelope';

interface S2StrategyViewProps {
  viewModel: PlanViewModel;
  /** @deprecated Header is now rendered by StrategyStageRenderer */
  destinationCard?: DestinationCard;
  onRefineAssumptions?: () => void;
  /** @deprecated CTA is now rendered by NextStepBar */
  canExpandToItinerary?: boolean;
}

function StrategySectionCard({ section }: { section: StrategySection }) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  return (
    <div className="bg-card rounded-lg border border-border overflow-hidden shadow-sm">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-muted/50 transition-colors"
      >
        <span className="text-sm font-medium text-card-foreground">
          {section.title}
        </span>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        )}
      </button>

      {isExpanded && section.bullets.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-border/50">
          <ul className="space-y-1.5">
            {section.bullets.slice(0, 6).map((bullet, idx) => (
              <li
                key={idx}
                className="text-xs text-muted-foreground flex items-start gap-2"
              >
                <span className="text-muted-foreground/50 mt-1">-</span>
                <span>{bullet}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function OpenDecisionsPanel({ decisions }: { decisions: OpenDecision[] }) {
  if (decisions.length === 0) return null;

  const blockingCount = decisions.filter(d => d.is_blocking).length;

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
          <li
            key={decision.id}
            className="flex items-start gap-2"
          >
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
          <p className="text-xs text-muted-foreground">Strategy is being prepared...</p>
        </div>
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-card rounded-lg border border-border px-4 py-3 shadow-sm">
            <div className="h-4 bg-muted rounded w-2/3 animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col p-4 space-y-4">
      {/* Strategy summary for short strategies (1-2 sections) */}
      {strategy_sections.length > 0 && strategy_sections.length < 3 && (
        <div className="bg-card rounded-lg border border-border p-4 mb-2 shadow-sm">
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
            Strategy summary
          </h4>
          <ul className="text-sm text-card-foreground space-y-1">
            {strategy_sections.map(s => (
              <li key={s.id}>• {s.title}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Strategy sections - collapsed by default */}
      <div className="space-y-2">
        {strategy_sections.map((section) => (
          <StrategySectionCard key={section.id} section={section} />
        ))}
      </div>

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
