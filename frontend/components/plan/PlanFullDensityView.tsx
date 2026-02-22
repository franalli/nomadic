'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Brain, Building2, ChevronDown, Plane } from 'lucide-react';
import type { ReactNode } from 'react';
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { useMapSync } from '@/hooks/useMapSync';
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

const DESKTOP_MAP_CONTENT_STYLE = { minWidth: 480, maxWidth: 800 } as const;
interface PlanFullDensityViewProps {
  state: PlanViewState; viewModel: PlanViewModel; filteredViewModel: PlanViewModel;
  fullModeSections: PlanViewModel['strategy_sections']; fullModePOIs: MapPOI[];
  effectiveTiles: Record<string, Tile>; effectiveTripInputs: DocumentTripInputs | undefined;
  destinationCard?: DestinationCard; generation?: GenerationState | null;
  savedTileIds: Set<string>; hasSectionData: boolean; hasItineraryContent: boolean;
  isExpandingItinerary: boolean; isStreaming: boolean; isAnyRegenerating: boolean;
  isRegenUpdating: boolean; isDesktop: boolean; showConstraints: boolean;
  preferenceCount: number;
  effectiveMode: string; timelineVariant: TimelineVariant;
  timelineSectionRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onRefineAssumptions?: () => void;
  handleSaveTile: (tile: Tile) => Promise<void>;
  handleOpenBookingDrawer: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onOpenActivitySettings?: () => void; onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void; onToggleConstraints: () => void;
  staysExpanded: boolean; flightsExpanded: boolean;
  onToggleStays: () => void; onToggleFlights: () => void;
}

export function PlanFullDensityView({
  state, viewModel, filteredViewModel, fullModeSections, fullModePOIs,
  effectiveTiles, effectiveTripInputs, destinationCard, generation,
  savedTileIds, hasSectionData, hasItineraryContent, isExpandingItinerary,
  isStreaming, isAnyRegenerating, isRegenUpdating, isDesktop, showConstraints,
  preferenceCount, effectiveMode, timelineVariant,
  timelineSectionRef, scrollContainerRef, onRefineAssumptions, handleSaveTile, handleOpenBookingDrawer,
  onOpenActivitySettings, onOpenStaysSettings, onOpenFlightsSettings, onToggleConstraints,
  staysExpanded, flightsExpanded, onToggleStays, onToggleFlights,
}: PlanFullDensityViewProps): ReactNode {
  const effectiveFullDest = effectiveTripInputs?.destination ?? destinationCard?.title;
  const sectionFallbackPOIs = useMemo(
    () => fullModePOIs.length === 0
      ? extractPOIsFromSections(fullModeSections ?? [], effectiveFullDest)
      : [],
    [fullModePOIs, fullModeSections, effectiveFullDest]
  );
  const fullModeMapItems = useMemo(
    () => fullModePOIs.length > 0 ? fullModePOIs : sectionFallbackPOIs,
    [fullModePOIs, sectionFallbackPOIs]
  );

  // Derive destination center from the first hotel tile that has geo coordinates.
  // Hotels always come from Google Places so they reliably have lat/lng.
  const destinationCenter = useMemo(() => {
    const hotelTile = Object.values(effectiveTiles).find(
      (t) => (t.type === 'hotel' || t.type === 'accommodation') && t.geo?.lat && t.geo?.lng,
    );
    if (hotelTile?.geo) return { lat: hotelTile.geo.lat, lng: hotelTile.geo.lng, zoom: 13 };
    return null;
  }, [effectiveTiles]);

  const mapCenter = useMemo(
    () => fullModeMapItems.length > 0
      ? calculateMapCenter(fullModeMapItems)
      : (destinationCenter ?? { lat: 20, lng: 0, zoom: 2 }),
    [fullModeMapItems, destinationCenter]
  );
  const showDesktopMap = isDesktop && (fullModeMapItems.length > 0 || destinationCenter !== null);

  const handleMarkerClick = useCallback((itemId: string) => {
    const item = fullModeMapItems.find((i) => i.id === itemId);
    if (!item?.dayNumber) return;
    useMapSync.getState().requestScrollTo(item.dayNumber, itemId);
  }, [fullModeMapItems]);

  const stayCount = useMemo(
    () => Object.values(effectiveTiles).filter(t =>
      t.type === 'hotel' || t.type === 'stay' || t.type === 'accommodation'
    ).length,
    [effectiveTiles]
  );

  const flightCount = useMemo(
    () => Object.values(effectiveTiles).filter(t => t.type === 'flight').length,
    [effectiveTiles]
  );

  // Measure the spacer height so the map top-aligns with Day 1.
  //
  // The map column sits inside flexRowRef. sticky top-0 snaps the map to the
  // scroll container's top edge (just below PlanHeader) when the user scrolls.
  //
  // Spacer = distance from the flex row top to the timeline section top.
  // Using the flex row (not the scroll container) as reference is correct because
  // the spacer div lives inside the map column which starts at the flex row top.
  //
  // Map height = calc(100vh - headerOffset) where headerOffset is the scroll
  // container's distance from the viewport top (= PlanHeader height). This fills
  // the scroll container's visible viewport exactly after the map sticks.
  const specialistCount = useMemo(() => {
    return (fullModeSections ?? []).filter((section) => {
      const specialistType = section.specialist_type || '';
      const isGeneralType = specialistType === 'general' || specialistType === 'local_expert';
      if (isGeneralType) return true;
      return (section.content_added?.length ?? 0) > 0;
    }).length;
  }, [fullModeSections]);

  const flexRowRef = useRef<HTMLDivElement>(null);
  const contentColRef = useRef<HTMLDivElement>(null);
  const [mapSpacerHeight, setMapSpacerHeight] = useState(0);
  const [headerOffset, setHeaderOffset] = useState(0);
  useLayoutEffect(() => {
    const contentCol = contentColRef.current;
    const scrollContainer = scrollContainerRef.current;
    if (!contentCol || !scrollContainer) return;

    const measure = () => {
      const flexRow = flexRowRef.current;
      const timelineSection = timelineSectionRef.current;
      const scrollRect = scrollContainer.getBoundingClientRect();
      // PlanHeader height = scroll container's distance from viewport top.
      // Used to correctly size the sticky map: calc(100vh - headerOffset).
      setHeaderOffset(Math.round(scrollRect.top));

      if (!flexRow || !timelineSection) {
        // Timeline not mounted yet — map starts flush with content column top
        setMapSpacerHeight(0);
        return;
      }
      const rowRect = flexRow.getBoundingClientRect();
      const sectionRect = timelineSection.getBoundingClientRect();
      // Spacer = flex row top → timeline section top (content above Day 1).
      const h = sectionRect.top - rowRect.top;
      setMapSpacerHeight(Math.max(0, h));
    };

    const observer = new ResizeObserver(measure);
    observer.observe(contentCol);
    // Measure immediately and after content settles
    measure();
    const t1 = setTimeout(measure, 100);
    const t2 = setTimeout(measure, 500);
    return () => { observer.disconnect(); clearTimeout(t1); clearTimeout(t2); };

  }, [hasItineraryContent, showConstraints, staysExpanded, flightsExpanded, stayCount, flightCount, specialistCount, showDesktopMap, scrollContainerRef, timelineSectionRef]);

  return (
    <div className="flex flex-col">
      {/* Content + map — side by side, map top-aligned with Day 1 */}
      <div ref={flexRowRef} className={cn('flex', showDesktopMap && 'gap-6')}>
        <div
          ref={contentColRef}
          className={cn('flex flex-col min-w-0', showDesktopMap ? 'flex-1' : 'w-full')}
          style={showDesktopMap ? DESKTOP_MAP_CONTENT_STYLE : undefined}
        >
          <PlanSpecialistsSection
            viewModel={viewModel} filteredViewModel={filteredViewModel}
            fullModeSections={fullModeSections} effectiveTiles={effectiveTiles}
            effectiveTripInputs={effectiveTripInputs} destinationCard={destinationCard}
            hasItineraryContent={hasItineraryContent} isAnyRegenerating={isAnyRegenerating}
            isRegenUpdating={isRegenUpdating} showConstraints={showConstraints}
            onRefineAssumptions={onRefineAssumptions} onOpenActivitySettings={onOpenActivitySettings}
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

        {/* Filter chips row — Specialists + Flights + Stays, flush with day cards */}
        {hasItineraryContent && (specialistCount > 0 || flightCount > 0 || stayCount > 0) && (
          <div className="flex items-center gap-2 px-4 pb-2 pt-1">
            {specialistCount > 0 && (
              <button
                type="button"
                onClick={onToggleConstraints}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-sm whitespace-nowrap transition-colors',
                  'border-zinc-600/50 bg-transparent text-zinc-400 hover:bg-zinc-800/50',
                )}
              >
                <Brain className="w-3.5 h-3.5" />
                Specialists ({specialistCount})
                <ChevronDown className={cn('w-3 h-3 transition-transform', showConstraints && 'rotate-180')} />
              </button>
            )}
            {flightCount > 0 && (
              <button
                type="button"
                onClick={onToggleFlights}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-sm whitespace-nowrap transition-colors border-zinc-600/50 bg-transparent text-zinc-400 hover:bg-zinc-800/50"
              >
                <Plane className="w-3.5 h-3.5" />
                Flights ({flightCount})
                <ChevronDown className={cn('w-3 h-3 transition-transform', flightsExpanded && 'rotate-180')} />
              </button>
            )}
            {stayCount > 0 && (
              <button
                type="button"
                onClick={onToggleStays}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-sm whitespace-nowrap transition-colors border-zinc-600/50 bg-transparent text-zinc-400 hover:bg-zinc-800/50"
              >
                <Building2 className="w-3.5 h-3.5" />
                Stays ({stayCount})
                <ChevronDown className={cn('w-3 h-3 transition-transform', staysExpanded && 'rotate-180')} />
              </button>
            )}
          </div>
        )}

        <AnimatePresence>
          {effectiveTiles && Object.keys(effectiveTiles).length > 0 && (
            <motion.section
              key="tiles-section" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              transition={{ duration: REVEAL_TIMING.TILES_FADE / 1000 }}
              id="tiles-section"
              className={cn('mt-1', isExpandingItinerary && 'opacity-60 pointer-events-none')}
            >
              <BookingSection
                state={state} tiles={effectiveTiles} generation={generation}
                hasStrategyContent={hasSectionData} savedTileIds={savedTileIds}
                onSaveTile={handleSaveTile} hasDates={!!effectiveTripInputs?.start_date}
                mode={effectiveMode as 'planning' | 'booking'}
                strategySections={viewModel.strategy_sections}
                onOpenStaysSettings={onOpenStaysSettings}
                isExpanded={staysExpanded}
                onToggleExpanded={onToggleStays}
                flightsExpanded={flightsExpanded}
                onToggleFlights={onToggleFlights}
              />
            </motion.section>
          )}
        </AnimatePresence>

        {!isDesktop && hasItineraryContent && (fullModePOIs.length > 0 || destinationCenter !== null) && (
          <section className="mt-4 px-4">
            <div className="h-[300px] overflow-hidden rounded-xl border border-zinc-200/50 dark:border-white/10">
              <MapErrorBoundary className="h-full w-full">
                <InteractiveMap items={fullModeMapItems} activeItemId={null}
                  defaultCenter={mapCenter} className="h-full w-full"
                  interactive={false} showAttribution={false} />
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
              transition={{ duration: REVEAL_TIMING.MAP_FADE / 1000, delay: REVEAL_TIMING.MAP_DELAY / 1000, ease: [0.4, 0, 0.2, 1] }} className="flex-1 min-w-[350px] self-stretch"
            >
              {/* Spacer pushes map down so sticky top-0 aligns with Day 1 */}
              <div style={{ height: mapSpacerHeight }} />
              <div className="sticky overflow-hidden" style={{ top: `${headerOffset}px`, height: `calc(100vh - ${headerOffset}px)` }}>
                <div className="h-full w-full">
                  <MapErrorBoundary className="h-full w-full">
                    <InteractiveMap
                      items={fullModeMapItems}
                      activeItemId={null}
                      defaultCenter={mapCenter}
                      className="h-full w-full"
                      onMarkerClick={handleMarkerClick}
                    />
                  </MapErrorBoundary>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
