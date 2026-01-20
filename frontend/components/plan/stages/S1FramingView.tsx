/**
 * S1FramingView
 *
 * Framing state view - skeleton structure, no days/prices.
 * Shows trip intent and draft structure being created.
 */

'use client';

import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';

interface S1FramingViewProps {
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
}

export function S1FramingView({
  viewModel,
  destinationCard,
}: S1FramingViewProps) {
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

      {/* Status indicator */}
      <div className="flex items-center gap-2 text-zinc-400">
        <div className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
        <span className="text-sm">Creating draft structure...</span>
      </div>

      {/* Skeleton content - max 5 lines per spec */}
      <div className="flex-1 space-y-3">
        <div className="bg-zinc-800/30 rounded-lg p-4 border border-zinc-700/30">
          <div className="space-y-2">
            <div className="h-3 bg-zinc-700/50 rounded w-3/4 animate-pulse" />
            <div className="h-3 bg-zinc-700/50 rounded w-1/2 animate-pulse" />
            <div className="h-3 bg-zinc-700/50 rounded w-2/3 animate-pulse" />
          </div>
        </div>

        {/* Strategy sections preview (if any) */}
        {viewModel.strategy_sections && viewModel.strategy_sections.length > 0 && (
          <div className="space-y-2">
            {viewModel.strategy_sections.slice(0, 2).map((section) => (
              <div
                key={section.id}
                className="bg-zinc-800/20 rounded-lg p-3 border border-zinc-700/20"
              >
                <p className="text-xs text-zinc-500 font-medium">
                  {section.title}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer hint */}
      <div className="text-center pt-2">
        <p className="text-zinc-500 text-xs">
          Ready to generate strategy
        </p>
      </div>
    </div>
  );
}

export default S1FramingView;
