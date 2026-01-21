/**
 * S1FramingView
 *
 * Framing state view - skeleton structure, no days/prices.
 * Shows trip intent and draft structure being created.
 */

'use client';

import { Sparkles } from 'lucide-react';
import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';

interface S1FramingViewProps {
  viewModel: PlanViewModel;
  destinationCard?: DestinationCard;
  isGenerating?: boolean;
  onGenerateStrategy?: () => void;
}

export function S1FramingView({
  viewModel,
  destinationCard,
  isGenerating = false,
  onGenerateStrategy,
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
        <span className="text-sm">
          {isGenerating ? 'Building your plan...' : 'Structure ready'}
        </span>
      </div>

      {/* Progress stepper */}
      <div className="flex items-center justify-center gap-2 py-2">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-xs text-zinc-400">Structure</span>
        </div>
        <div className="w-4 h-px bg-zinc-700" />
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${isGenerating ? 'bg-amber-500 animate-pulse' : 'bg-zinc-600'}`} />
          <span className="text-xs text-zinc-500">Strategy</span>
        </div>
        <div className="w-4 h-px bg-zinc-700" />
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full bg-zinc-600" />
          <span className="text-xs text-zinc-500">Itinerary</span>
        </div>
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

      {/* Generate strategy button */}
      {!isGenerating && onGenerateStrategy && (
        <div className="text-center pt-4">
          <button
            type="button"
            onClick={onGenerateStrategy}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-amber-500 hover:bg-amber-600 text-white rounded-lg font-medium transition-colors shadow-lg shadow-amber-500/20"
          >
            <Sparkles className="h-4 w-4" />
            Generate strategy
          </button>
        </div>
      )}
    </div>
  );
}

export default S1FramingView;
