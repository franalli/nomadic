'use client';

import { AnimatePresence, motion } from 'framer-motion';

import { REVEAL_TIMING } from '@/lib/animation-config';
import { cn } from '@/lib/utils';
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
}: PlanFullDensityTilesSectionProps) {
  if (Object.keys(effectiveTiles).length === 0) return null;

  return (
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
  );
}
