/**
 * S3EditingView
 *
 * Editing state view - shows stale itinerary with refresh CTA.
 * User has changed constraints and itinerary needs to be regenerated.
 */

'use client';

import { AlertCircle,RefreshCw } from 'lucide-react';

import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';

interface S3EditingViewProps {
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
  onRefresh?: () => void;
}

export function S3EditingView({
  viewModel,
  destinationCard: _destinationCard,
  onRefresh,
}: S3EditingViewProps) {
  const { day_cards = [], itinerary_overview } = viewModel;

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      {/* Note: Destination card removed - PlanHeader owns destination display */}

      {/* Stale indicator */}
      <div className="bg-amber-900/20 rounded-lg border border-amber-700/30 p-3 flex items-center gap-2">
        <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
        <p className="text-xs text-amber-200">
          Constraints changed - itinerary needs refresh
        </p>
      </div>

      {/* Overview (dimmed) */}
      {itinerary_overview && (
        <div className="bg-zinc-800/20 rounded-lg border border-zinc-700/20 p-3 opacity-60">
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span>{itinerary_overview.duration_label}</span>
            <span className="text-zinc-600">-</span>
            <span>{itinerary_overview.base_structure}</span>
          </div>
        </div>
      )}

      {/* Stale day cards summary (dimmed) */}
      <div className="flex-1 space-y-2 opacity-50">
        {day_cards.map((card) => (
          <div
            key={card.day_number}
            className="bg-zinc-800/30 rounded-lg border border-zinc-700/30 px-4 py-3"
          >
            <div className="flex items-center gap-3">
              <span className="text-xs text-zinc-600 bg-zinc-700/30 px-2 py-0.5 rounded">
                Day {card.day_number}
              </span>
              <span className="text-sm text-zinc-500">
                {card.label}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Refresh CTA */}
      <div className="pt-2">
        <button
          onClick={onRefresh}
          className="w-full py-2.5 px-4 rounded-lg text-sm font-medium bg-amber-600 hover:bg-amber-500 text-white transition-colors flex items-center justify-center gap-2"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh itinerary
        </button>
      </div>
    </div>
  );
}

export default S3EditingView;
