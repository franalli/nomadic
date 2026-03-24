'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, ChevronUp, ShoppingBag } from 'lucide-react';

import { REVEAL_TIMING } from '@/lib/animation-config';
import { cn } from '@/lib/utils';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { GenerationState, PlanViewState, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { BookingSection } from './BookingSection';

const FADE_INITIAL = { opacity: 0 } as const;
const FADE_VISIBLE = { opacity: 1 } as const;
const TILES_TRANSITION = { duration: REVEAL_TIMING.TILES_FADE / 1000 } as const;

interface PlanFullDensityTilesSectionProps {
  state: PlanViewState;
  effectiveTiles: Record<string, Tile>;
  generation?: GenerationState | null;
  hasSectionData: boolean;
  savedTileIds: Set<string>;
  hasDates: boolean;
  effectiveMode: 'planning' | 'booking';
  effectiveStrategySections: StrategySection[] | undefined;
  onOpenStaysSettings?: () => void;
  staysExpanded: boolean;
  onToggleStays: () => void;
  flightsExpanded: boolean;
  onToggleFlights: () => void;
  onSaveTile: (tile: Tile) => Promise<void>;
  isExpandingItinerary: boolean;
  hasItineraryContent: boolean;
}

export function PlanFullDensityTilesSection({
  state,
  effectiveTiles,
  generation,
  hasSectionData,
  savedTileIds,
  hasDates,
  effectiveMode,
  effectiveStrategySections,
  onOpenStaysSettings,
  staysExpanded,
  onToggleStays,
  flightsExpanded,
  onToggleFlights,
  onSaveTile,
  isExpandingItinerary,
  hasItineraryContent,
}: PlanFullDensityTilesSectionProps) {
  const tileCount = Object.keys(effectiveTiles).length;
  const tilesSectionExpanded = usePanelToggleStore((s) => s.tilesSectionExpanded);
  const toggleTilesSection = usePanelToggleStore((s) => s.toggleTilesSection);

  if (tileCount === 0) return null;

  const isCollapsible = hasItineraryContent;
  const showContent = !isCollapsible || tilesSectionExpanded;

  return (
    <div>
      {isCollapsible && (
        <button
          onClick={toggleTilesSection}
          className={cn(
            'flex w-full items-center justify-between px-4 py-3',
            'text-sm font-medium text-zinc-600 dark:text-white/60',
            'hover:bg-zinc-50 dark:hover:bg-white/5 transition-colors rounded-lg'
          )}
        >
          <span className="flex items-center gap-2">
            <ShoppingBag className="h-4 w-4" />
            Browse flights, stays & activities
            {tileCount > 0 && (
              <span className="text-xs text-zinc-400 dark:text-white/30">
                ({tileCount})
              </span>
            )}
          </span>
          {tilesSectionExpanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>
      )}

      {showContent && (
        <AnimatePresence>
          <motion.section
            key="tiles-section"
            initial={FADE_INITIAL}
            animate={FADE_VISIBLE}
            transition={TILES_TRANSITION}
            id="tiles-section"
            className={cn('mt-1', isExpandingItinerary && 'pointer-events-none opacity-50')}
          >
            <BookingSection
              state={state}
              tiles={effectiveTiles}
              generation={generation}
              hasStrategyContent={hasSectionData}
              savedTileIds={savedTileIds}
              onSaveTile={onSaveTile}
              hasDates={hasDates}
              mode={effectiveMode}
              strategySections={effectiveStrategySections}
              onOpenStaysSettings={onOpenStaysSettings}
              isExpanded={staysExpanded}
              onToggleExpanded={onToggleStays}
              flightsExpanded={flightsExpanded}
              onToggleFlights={onToggleFlights}
            />
          </motion.section>
        </AnimatePresence>
      )}
    </div>
  );
}
