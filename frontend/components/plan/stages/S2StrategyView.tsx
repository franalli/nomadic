/**
 * S2StrategyView
 *
 * Strategy ready state - shows strategy sections (collapsed) and open decisions.
 * This is the main planning view before itinerary generation.
 */

'use client';

import React from 'react';
import { ChevronDown, ChevronRight, AlertCircle } from 'lucide-react';
import type { DestinationCard, PlanViewModel, StrategySection, OpenDecision } from '@/types/plan-envelope';

interface S2StrategyViewProps {
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
  onExpandToItinerary?: () => void;
  onRefineAssumptions?: () => void;
  canExpandToItinerary: boolean;
}

function StrategySectionCard({ section }: { section: StrategySection }) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  return (
    <div className="bg-zinc-800/40 rounded-lg border border-zinc-700/50 overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-zinc-700/20 transition-colors"
      >
        <span className="text-sm font-medium text-zinc-200">
          {section.title}
        </span>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-zinc-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-400" />
        )}
      </button>

      {isExpanded && section.bullets.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-zinc-700/30">
          <ul className="space-y-1.5">
            {section.bullets.slice(0, 6).map((bullet, idx) => (
              <li
                key={idx}
                className="text-xs text-zinc-400 flex items-start gap-2"
              >
                <span className="text-zinc-600 mt-1">-</span>
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
    <div className="bg-amber-900/20 rounded-lg border border-amber-700/30 p-4">
      <div className="flex items-center gap-2 mb-3">
        <AlertCircle className="w-4 h-4 text-amber-500" />
        <h3 className="text-sm font-medium text-amber-200">
          Open decisions
          {blockingCount > 0 && (
            <span className="text-amber-400 ml-1">
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
                decision.is_blocking ? 'bg-amber-500' : 'bg-zinc-500'
              }`}
            />
            <span className="text-xs text-zinc-300">
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
  destinationCard,
  onExpandToItinerary,
  onRefineAssumptions,
  canExpandToItinerary,
}: S2StrategyViewProps) {
  const { strategy_sections = [], open_decisions = [] } = viewModel;

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      {/* Destination card */}
      {destinationCard && (
        <div className="bg-zinc-800/50 rounded-lg p-4 border border-zinc-700/50">
          <h2 className="text-lg font-medium text-zinc-100">
            {destinationCard.title}
          </h2>
          {destinationCard.subtitle && (
            <p className="text-sm text-zinc-400 mt-1">
              {destinationCard.subtitle}
            </p>
          )}
        </div>
      )}

      {/* Strategy sections - collapsed by default */}
      <div className="flex-1 space-y-2 overflow-y-auto">
        {strategy_sections.map((section) => (
          <StrategySectionCard key={section.id} section={section} />
        ))}
      </div>

      {/* Open decisions panel */}
      <OpenDecisionsPanel decisions={open_decisions} />

      {/* CTAs */}
      <div className="flex flex-col gap-2 pt-2">
        <button
          onClick={onExpandToItinerary}
          disabled={!canExpandToItinerary}
          className={`w-full py-2.5 px-4 rounded-lg text-sm font-medium transition-colors ${
            canExpandToItinerary
              ? 'bg-blue-600 hover:bg-blue-500 text-white'
              : 'bg-zinc-700 text-zinc-400 cursor-not-allowed'
          }`}
        >
          Expand to itinerary
        </button>
        <button
          onClick={onRefineAssumptions}
          className="w-full py-2 px-4 rounded-lg text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 transition-colors"
        >
          Refine assumptions
        </button>
      </div>
    </div>
  );
}

export default S2StrategyView;
