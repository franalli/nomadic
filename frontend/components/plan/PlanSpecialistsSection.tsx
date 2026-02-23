'use client';

/**
 * PlanSpecialistsSection
 *
 * Destination intelligence section for full-density plan view.
 * Renders trip-level travel intel (no specialist branding) and regeneration overlay.
 */

import type { ReactNode } from 'react';

import type { PlanViewModel } from '@/types/plan-envelope';

import { DestinationIntelCard } from './DestinationIntelCard';

interface PlanSpecialistsSectionProps {
  sections: PlanViewModel['strategy_sections'];
  destination?: string | null;
  isAnyRegenerating: boolean;
  isRegenUpdating: boolean;
}

export function PlanSpecialistsSection({
  sections,
  destination,
  isAnyRegenerating,
  isRegenUpdating,
}: PlanSpecialistsSectionProps): ReactNode {
  const hasSections = (sections?.length ?? 0) > 0;

  return (
    <section id="specialists-section" className="relative">
      {hasSections && <DestinationIntelCard destination={destination} sections={sections ?? []} />}

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
