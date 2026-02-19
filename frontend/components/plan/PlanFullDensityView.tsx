'use client';

import { AnimatePresence, motion } from 'framer-motion';
import type { ReactNode } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { REVEAL_TIMING } from '@/lib/animation-config';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import { calculateMapCenter, extractPOIsFromSections } from '@/lib/ghost-timeline-adapter';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { BookingSection } from './BookingSection';
import { OriginPromptCard } from './OriginPromptCard';
import { PlanSpecialistsSection } from './PlanSpecialistsSection';
import type { GenerationState } from './planStateHelpers';
import { PlanTimelineSection } from './PlanTimelineSection';
import { type TimelineVariant } from './TimelineThread';

const DESKTOP_MAP_CONTENT_STYLE = { minWidth: 720, maxWidth: 900 } as const;

interface PlanFullDensityViewProps {
  state: PlanViewState; viewModel: PlanViewModel; filteredViewModel: PlanViewModel;
  fullModeSections: PlanViewModel['strategy_sections']; fullModePOIs: MapPOI[];
  effectiveTiles: Record<string, Tile>; effectiveTripInputs: DocumentTripInputs | undefined;
  destinationCard?: DestinationCard; generation?: GenerationState | null;
  savedTileIds: Set<string>; hasSectionData: boolean; hasItineraryContent: boolean;
  isExpandingItinerary: boolean; isStreaming: boolean; isAnyRegenerating: boolean;
  isRegenUpdating: boolean; isDesktop: boolean; showConstraints: boolean;
  preferenceCount: number; validatedRules: Set<string>; violatedRules: Set<string>;
  effectiveMode: string; timelineVariant: TimelineVariant;
  timelineSectionRef: React.RefObject<HTMLDivElement | null>;
  onRefineAssumptions?: () => void;
  handleSaveTile: (tile: Tile) => Promise<void>;
  handleOpenBookingDrawer: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onOpenActivitySettings?: () => void; onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void; onToggleConstraints: () => void;
}

export function PlanFullDensityView({
  state, viewModel, filteredViewModel, fullModeSections, fullModePOIs,
  effectiveTiles, effectiveTripInputs, destinationCard, generation,
  savedTileIds, hasSectionData, hasItineraryContent, isExpandingItinerary,
  isStreaming, isAnyRegenerating, isRegenUpdating, isDesktop, showConstraints,
  preferenceCount, validatedRules, violatedRules, effectiveMode, timelineVariant,
  timelineSectionRef, onRefineAssumptions, handleSaveTile, handleOpenBookingDrawer,
  onOpenActivitySettings, onOpenStaysSettings, onOpenFlightsSettings, onToggleConstraints,
}: PlanFullDensityViewProps): ReactNode {
  const effectiveFullDest = effectiveTripInputs?.destination ?? destinationCard?.title;
  const sectionFallbackPOIs = fullModePOIs.length === 0
    ? extractPOIsFromSections(fullModeSections ?? [], effectiveFullDest) : [];
  const fullModeMapItems = fullModePOIs.length > 0 ? fullModePOIs : sectionFallbackPOIs;
  const mapCenter = fullModeMapItems.length > 0
    ? calculateMapCenter(fullModeMapItems) : { lat: 20, lng: 0, zoom: 2 };
  const showDesktopMap = isDesktop && fullModeMapItems.length > 0;

  return (
    <div className={cn('flex', showDesktopMap && 'gap-6')}>
      <div
        className={cn('flex flex-col min-w-0', showDesktopMap ? 'flex-1' : 'w-full')}
        style={showDesktopMap ? DESKTOP_MAP_CONTENT_STYLE : undefined}
      >
        <PlanSpecialistsSection
          viewModel={viewModel} filteredViewModel={filteredViewModel}
          fullModeSections={fullModeSections} effectiveTiles={effectiveTiles}
          effectiveTripInputs={effectiveTripInputs} destinationCard={destinationCard}
          hasItineraryContent={hasItineraryContent} isAnyRegenerating={isAnyRegenerating}
          isRegenUpdating={isRegenUpdating} showConstraints={showConstraints}
          validatedRules={validatedRules} violatedRules={violatedRules}
          onRefineAssumptions={onRefineAssumptions} onOpenActivitySettings={onOpenActivitySettings}
          onToggleConstraints={onToggleConstraints}
        />

        {state === 'S2_STRATEGY_READY' &&
          effectiveTripInputs?.destination && effectiveTripInputs?.start_date &&
          effectiveTripInputs?.end_date && !effectiveTripInputs?.origin &&
          (viewModel.executed_strategy_topics?.length ?? 0) >= 2 && (
            <div className="px-4 mb-4">
              <OriginPromptCard
                onSetOrigin={(origin) => { useDocumentStore.getState().commitTripInputs({ origin }); }}
              />
            </div>
          )}

        <AnimatePresence>
          {effectiveTiles && Object.keys(effectiveTiles).length > 0 && (
            <motion.section
              key="tiles-section" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              transition={{ duration: REVEAL_TIMING.TILES_FADE / 1000 }}
              id="tiles-section"
              className={cn('mt-4 px-4', isExpandingItinerary && 'opacity-60 pointer-events-none')}
            >
              <BookingSection
                state={state} tiles={effectiveTiles} generation={generation}
                hasStrategyContent={hasSectionData} savedTileIds={savedTileIds}
                onSaveTile={handleSaveTile} hasDates={!!effectiveTripInputs?.start_date}
                mode={effectiveMode as 'planning' | 'booking'}
                strategySections={viewModel.strategy_sections}
                onOpenStaysSettings={onOpenStaysSettings}
              />
            </motion.section>
          )}
        </AnimatePresence>

        {!isDesktop && hasItineraryContent && fullModePOIs.length > 0 && (
          <section className="mt-4 px-4">
            <div className="h-[300px] overflow-hidden rounded-xl border border-border/50">
              <MapErrorBoundary className="h-full w-full">
                <InteractiveMap items={fullModeMapItems} activeItemId={null}
                  defaultCenter={mapCenter} className="h-full w-full" />
              </MapErrorBoundary>
            </div>
          </section>
        )}

        <PlanTimelineSection
          dayCards={viewModel.day_cards ?? []} timelineVariant={timelineVariant}
          isStreaming={isStreaming} isRegenUpdating={isRegenUpdating}
          isExpandingItinerary={isExpandingItinerary} hasItineraryContent={hasItineraryContent}
          preferenceCount={preferenceCount} savedTileIds={savedTileIds}
          timelineSectionRef={timelineSectionRef}
          handleOpenBookingDrawer={handleOpenBookingDrawer}
          onOpenStaysSettings={onOpenStaysSettings} onOpenFlightsSettings={onOpenFlightsSettings}
        />
      </div>

      <AnimatePresence>
        {showDesktopMap && (
          <motion.div key="desktop-map" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }} className="w-[400px] max-w-[35vw] shrink-0"
          >
            <div className="sticky top-0 h-screen overflow-hidden">
              <div className="h-full w-full">
                <MapErrorBoundary className="h-full w-full">
                  <InteractiveMap items={fullModeMapItems} activeItemId={null}
                    defaultCenter={mapCenter} className="h-full w-full" />
                </MapErrorBoundary>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
