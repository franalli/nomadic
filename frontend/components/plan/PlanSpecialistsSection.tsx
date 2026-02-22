'use client';

/**
 * PlanSpecialistsSection
 *
 * Specialists section for full-density plan view.
 * Shows strategy cards and regeneration overlay.
 * StrategyConstraintBar is rendered above this in PlanFullDensityView
 * so it spans the full panel width (content + map).
 */

import type { ReactNode } from 'react';

import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { S2StrategyView } from './stages/S2StrategyView';

interface PlanSpecialistsSectionProps {
  viewModel: PlanViewModel;
  filteredViewModel: PlanViewModel;
  fullModeSections: PlanViewModel['strategy_sections'];
  effectiveTiles: Record<string, Tile>;
  effectiveTripInputs: DocumentTripInputs | undefined;
  destinationCard?: DestinationCard;
  hasItineraryContent: boolean;
  isAnyRegenerating: boolean;
  isRegenUpdating: boolean;
  showConstraints: boolean;
  onRefineAssumptions?: () => void;
  onOpenActivitySettings?: () => void;
}

export function PlanSpecialistsSection({
  viewModel,
  filteredViewModel,
  fullModeSections,
  effectiveTiles,
  effectiveTripInputs,
  destinationCard,
  hasItineraryContent,
  isAnyRegenerating,
  isRegenUpdating,
  showConstraints,
  onRefineAssumptions,
  onOpenActivitySettings,
}: PlanSpecialistsSectionProps): ReactNode {
  return (
    <section id="specialists-section" className="relative">
      {(fullModeSections?.length ?? 0) > 0 && (
        <>
          {!hasItineraryContent ? (
            <S2StrategyView
              key={`strategy-${destinationCard?.title}`}
              viewModel={filteredViewModel}
              onRefineAssumptions={onRefineAssumptions}
              pendingTopics={viewModel.pending_strategy_topics}
              executedTopics={viewModel.executed_strategy_topics}
              tiles={effectiveTiles}
              tripInputs={effectiveTripInputs}
              density="full"
              onOpenActivitySettings={onOpenActivitySettings}
            />
          ) : (
            showConstraints && (
              <S2StrategyView
                key={`strategy-${destinationCard?.title}`}
                viewModel={filteredViewModel}
                onRefineAssumptions={onRefineAssumptions}
                pendingTopics={viewModel.pending_strategy_topics}
                executedTopics={viewModel.executed_strategy_topics}
                tiles={effectiveTiles}
                tripInputs={effectiveTripInputs}
                density="full"
                onOpenActivitySettings={onOpenActivitySettings}
              />
            )
          )}
        </>
      )}

      {/* Regeneration overlay */}
      {isAnyRegenerating && (
        <div className="absolute inset-0 z-10 flex items-start justify-center pt-20 bg-white/60 dark:bg-zinc-950/60 backdrop-blur-[1px]">
          <div className="flex flex-col items-center gap-4 rounded-lg bg-white/90 dark:bg-zinc-900/90 px-6 py-4 shadow-card border border-zinc-200 dark:border-white/10">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
            <p className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
              {isRegenUpdating ? 'Updating itinerary...' : 'Updating plan...'}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
