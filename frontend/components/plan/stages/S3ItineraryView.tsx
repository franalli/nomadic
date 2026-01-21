/**
 * S3ItineraryView
 *
 * Itinerary ready state - shows day cards and overview.
 * Day cards are collapsed by default, max 1 expanded at a time.
 */

'use client';

import React from 'react';
import { ChevronDown, ChevronRight, Sun, Sunset, Moon } from 'lucide-react';
import type {
  DestinationCard,
  PlanViewModel,
  DayCard,
  DayBlock,
  ItineraryOverview,
} from '@/types/plan-envelope';

interface S3ItineraryViewProps {
  viewModel: PlanViewModel;
  /** Kept for context but not rendered (header owns destination display) */
  destinationCard?: DestinationCard;
}

function PeriodIcon({ period }: { period: DayBlock['period'] }) {
  const iconClass = "w-3 h-3";
  switch (period) {
    case 'morning':
      return <Sun className={`${iconClass} text-amber-400`} />;
    case 'afternoon':
      return <Sunset className={`${iconClass} text-orange-400`} />;
    case 'evening':
      return <Moon className={`${iconClass} text-blue-400`} />;
    default:
      return null;
  }
}

function DayCardComponent({
  card,
  isExpanded,
  onToggle,
}: {
  card: DayCard;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="bg-zinc-800/40 rounded-lg border border-zinc-700/50 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-zinc-700/20 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-zinc-500 bg-zinc-700/50 px-2 py-0.5 rounded">
            Day {card.day_number}
          </span>
          <span className="text-sm text-zinc-200">
            {card.label}
          </span>
        </div>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-zinc-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-zinc-400" />
        )}
      </button>

      {isExpanded && card.blocks.length > 0 && (
        <div className="px-4 pb-3 pt-1 border-t border-zinc-700/30 space-y-2">
          {card.blocks.slice(0, 3).map((block, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2 py-1"
            >
              <PeriodIcon period={block.period} />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-zinc-300 capitalize">
                    {block.period}
                  </span>
                  {block.intensity && (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      block.intensity === 'light' ? 'bg-green-900/30 text-green-400' :
                      block.intensity === 'moderate' ? 'bg-amber-900/30 text-amber-400' :
                      'bg-red-900/30 text-red-400'
                    }`}>
                      {block.intensity}
                    </span>
                  )}
                </div>
                <p className="text-xs text-zinc-400 mt-0.5">
                  {block.summary}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function OverviewCard({ overview }: { overview: ItineraryOverview }) {
  return (
    <div className="bg-zinc-800/30 rounded-lg border border-zinc-700/30 p-3">
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        <span>{overview.duration_label}</span>
        <span className="text-zinc-600">-</span>
        <span>{overview.base_structure}</span>
        <span className="text-zinc-600">-</span>
        <span>{overview.activity_density}</span>
      </div>
    </div>
  );
}

export function S3ItineraryView({
  viewModel,
  destinationCard: _destinationCard,
}: S3ItineraryViewProps) {
  // destinationCard reserved for future use (header owns destination display)
  void _destinationCard;

  const { day_cards = [], itinerary_overview, itinerary_assumptions } = viewModel;
  const [expandedDay, setExpandedDay] = React.useState<number | null>(null);

  const handleToggleDay = (dayNumber: number) => {
    setExpandedDay(prev => prev === dayNumber ? null : dayNumber);
  };

  return (
    <div className="flex flex-col p-4 space-y-4">
      {/* Overview */}
      {itinerary_overview && (
        <OverviewCard overview={itinerary_overview} />
      )}

      {/* Day cards - collapsed by default, max 1 expanded */}
      <div className="space-y-2">
        {day_cards.map((card) => (
          <DayCardComponent
            key={card.day_number}
            card={card}
            isExpanded={expandedDay === card.day_number}
            onToggle={() => handleToggleDay(card.day_number)}
          />
        ))}
      </div>

      {/* Assumptions (collapsed summary) */}
      {itinerary_assumptions && itinerary_assumptions.assumptions.length > 0 && (
        <div className="bg-zinc-800/20 rounded-lg p-3 border border-zinc-700/20">
          <p className="text-xs text-zinc-500 mb-1">Assumptions</p>
          <p className="text-xs text-zinc-400">
            {itinerary_assumptions.assumptions[0]}
            {itinerary_assumptions.assumptions.length > 1 && (
              <span className="text-zinc-600">
                {' '}+{itinerary_assumptions.assumptions.length - 1} more
              </span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

export default S3ItineraryView;
