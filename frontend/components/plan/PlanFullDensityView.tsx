'use client';

import { AnimatePresence, motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { useLocalExpertPolling } from '@/hooks/useLocalExpertPolling';
import { useMapSync } from '@/hooks/useMapSync';
import { REVEAL_TIMING } from '@/lib/animation-config';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import { calculateMapCenter, extractPOIsFromSections } from '@/lib/ghost-timeline-adapter';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { BookingSection } from './BookingSection';
import { BookingSummary } from './BookingSummary';
import { FullDensityTimeline } from './FullDensityTimeline';
import { OriginPromptCard } from './OriginPromptCard';
import { PdfExportButton } from './PdfExportButton';
import { type GenerationState,isStrategyReady } from './planStateHelpers';
import { ShareTripButton } from './ShareTripButton';
import { type TimelineVariant } from './TimelineThread';

const DESKTOP_MAP_CONTENT_STYLE = { minWidth: 480, maxWidth: 800 } as const;

// Extracted animation constants to avoid re-creating objects on every render
const FADE_INITIAL = { opacity: 0 } as const;
const FADE_VISIBLE = { opacity: 1 } as const;
const TILES_TRANSITION = { duration: REVEAL_TIMING.TILES_FADE / 1000 } as const;
const MAP_TRANSITION = {
  duration: REVEAL_TIMING.MAP_FADE / 1000,
  delay: REVEAL_TIMING.MAP_DELAY / 1000,
  ease: [0.4, 0, 0.2, 1],
} as const;

interface PlanFullDensityViewProps {
  state: PlanViewState; viewModel: PlanViewModel;
  fullModeSections: PlanViewModel['strategy_sections']; fullModePOIs: MapPOI[];
  effectiveTiles: Record<string, Tile>; effectiveTripInputs: DocumentTripInputs | undefined;
  destinationCard?: DestinationCard; generation?: GenerationState | null;
  savedTileIds: Set<string>; hasSectionData: boolean; hasItineraryContent: boolean;
  isExpandingItinerary: boolean; isStreaming: boolean; isAnyRegenerating: boolean;
  isRegenUpdating: boolean; isDesktop: boolean;
  preferenceCount: number;
  effectiveMode: string; timelineVariant: TimelineVariant;
  timelineSectionRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  handleSaveTile: (tile: Tile) => Promise<void>;
  handleOpenBookingDrawer: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  onOpenSheet?: (sheet: SheetType) => void;
}

export function PlanFullDensityView({
  state, viewModel, fullModeSections, fullModePOIs,
  effectiveTiles, effectiveTripInputs, destinationCard, generation,
  savedTileIds, hasSectionData, hasItineraryContent, isExpandingItinerary,
  isStreaming, isAnyRegenerating, isRegenUpdating, isDesktop,
  preferenceCount, effectiveMode, timelineVariant,
  timelineSectionRef, scrollContainerRef, handleSaveTile, handleOpenBookingDrawer,
  onOpenStaysSettings, onOpenFlightsSettings, onOpenSheet: _onOpenSheet,
}: PlanFullDensityViewProps): ReactNode {
  const strategySections = useMemo(
    () => viewModel.strategy_sections ?? [],
    [viewModel.strategy_sections]
  );
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
      (t) => (t.type === 'hotel' || t.type === 'accommodation') && t.geo?.lat != null && t.geo?.lng != null,
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
  const venueLinksActions = useMemo(() => {
    const dayCards = viewModel.day_cards ?? [];
    if (dayCards.length === 0) return null;
    return (
      <>
        <ShareTripButton />
        <PdfExportButton
          tripInputs={effectiveTripInputs}
          dayCards={dayCards}
          tiles={effectiveTiles}
        />
      </>
    );
  }, [effectiveTiles, effectiveTripInputs, viewModel.day_cards]);

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

  const {
    staysExpanded,
    flightsExpanded,
    intelExpanded,
    onToggleStays,
    onToggleFlights,
    onToggleIntel,
  } = usePanelToggleStore(
    useShallow((s) => ({
      staysExpanded: s.staysExpanded,
      flightsExpanded: s.flightsExpanded,
      intelExpanded: s.intelExpanded,
      onToggleStays: s.toggleStays,
      onToggleFlights: s.toggleFlights,
      onToggleIntel: s.toggleIntel,
    }))
  );

  const localExpertSection = useMemo(
    () => strategySections.find((s) => s.specialist_type === 'local_expert'),
    [strategySections]
  );
  const localExpertSectionId = localExpertSection?.id ?? null;
  const localExpertHasTI = Boolean(
    localExpertSection?.travel_intelligence && Object.keys(localExpertSection.travel_intelligence).length > 0
  );
  const localExpertSectionEnrichment = (() => {
    const raw = localExpertSection?.local_expert_enrichment?.state;
    if (typeof raw !== 'string') return '';
    return raw.trim().toLowerCase();
  })();
  const localExpertReady = localExpertSectionEnrichment === 'ready';

  const {
    effectiveStrategySections,
    intelCategories,
    travelIntelItemCount,
    isTravelIntelPending,
    hasDestinationIntel,
  } = useLocalExpertPolling({
    strategySections,
    effectiveFullDest,
    isStreaming,
    localExpertSectionId,
    localExpertReady,
    localExpertHasTI,
    localExpertSection,
  });

  // Map sticky offset: distance from viewport top to scroll container top.
  // The sticky map fills calc(100vh - headerOffset) so it occupies the
  // scroll container's visible viewport exactly when it sticks.
  const flexRowRef = useRef<HTMLDivElement>(null);
  const contentColRef = useRef<HTMLDivElement>(null);
  const [headerOffset, setHeaderOffset] = useState(0);
  useLayoutEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) return;

    const measure = () => {
      const scrollRect = scrollContainer.getBoundingClientRect();
      setHeaderOffset(Math.round(scrollRect.top));
    };

    const observer = new ResizeObserver(measure);
    observer.observe(scrollContainer);
    measure();
    return () => { observer.disconnect(); };
  }, [scrollContainerRef]);

  const showTravelAdviceSegment = hasDestinationIntel || isTravelIntelPending;

  return (
    <div className="flex flex-col">
      {/* Mobile-only: TripSummaryPills (desktop pills live in the header) */}
      {!isDesktop && effectiveTripInputs && _onOpenSheet && (
        <div className="px-4 pb-2 pt-1">
          <TripSummaryPills
            tripInputs={effectiveTripInputs}
            dayCards={viewModel.day_cards}
            onOpenSheet={_onOpenSheet}
            disabled={isStreaming}
            flightCount={hasItineraryContent ? flightCount : 0}
            stayCount={hasItineraryContent ? stayCount : 0}
            travelAdviceCount={travelIntelItemCount}
            showTravelAdvice={showTravelAdviceSegment}
            isTravelAdvicePending={isTravelIntelPending}
            flightsActive={flightsExpanded}
            staysActive={staysExpanded}
            travelAdviceActive={intelExpanded}
            onToggleFlights={onToggleFlights}
            onToggleStays={onToggleStays}
            onToggleTravelAdvice={onToggleIntel}
          />
        </div>
      )}

      {/* Destination intel panel + regen status */}
      {hasDestinationIntel && (
        <div className="px-4 pb-2 pt-1">
          {hasDestinationIntel && intelExpanded && (
            <div
              id="destination-intel-panel"
              aria-labelledby="destination-intel-trigger"
              className="mt-2 rounded-xl border border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900/40"
            >
              <div className="max-h-[280px] space-y-3 overflow-y-auto px-3 py-3">
                {intelCategories.map((category) => (
                  <div key={category.key} className="space-y-1">
                    <p className="flex items-center gap-2 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                      <span>{category.icon}</span>
                      <span>{category.label}</span>
                    </p>
                    <ul className="list-disc list-outside marker:text-emerald-400 space-y-1 pl-10">
                      {category.items.map((item) => (
                        <li
                          key={`${category.key}-${item}`}
                          className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400"
                        >
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}

          {hasDestinationIntel && isAnyRegenerating && !isRegenUpdating && (
            <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-zinc-900/60 px-3 py-2">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
              <p className="text-xs text-zinc-600 dark:text-zinc-400">
                Updating plan...
              </p>
            </div>
          )}
        </div>
      )}

      {/* OriginPromptCard + BookingSection — full width above timeline+map row */}
      {isStrategyReady(state) &&
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
            key="tiles-section" initial={FADE_INITIAL} animate={FADE_VISIBLE}
            transition={TILES_TRANSITION}
            id="tiles-section"
            className={cn('mt-1', isExpandingItinerary && 'opacity-50 pointer-events-none')}
          >
            <BookingSection
              state={state} tiles={effectiveTiles} generation={generation}
              hasStrategyContent={hasSectionData} savedTileIds={savedTileIds}
              onSaveTile={handleSaveTile} hasDates={!!effectiveTripInputs?.start_date}
              mode={effectiveMode as 'planning' | 'booking'}
              strategySections={effectiveStrategySections}
              onOpenStaysSettings={onOpenStaysSettings}
              isExpanded={staysExpanded}
              onToggleExpanded={onToggleStays}
              flightsExpanded={flightsExpanded}
              onToggleFlights={onToggleFlights}
            />
          </motion.section>
        )}
      </AnimatePresence>

      {/* Timeline (left) + Map (right) — side by side, both start at same vertical position */}
      <div ref={flexRowRef} className={cn('flex', showDesktopMap && 'gap-6')}>
        <div
          ref={contentColRef}
          className={cn('flex flex-col min-w-0', showDesktopMap ? 'flex-1' : 'w-full')}
          style={showDesktopMap ? DESKTOP_MAP_CONTENT_STYLE : undefined}
        >
        <FullDensityTimeline
          viewModel={viewModel}
          hasItineraryContent={hasItineraryContent}
          isExpandingItinerary={isExpandingItinerary}
          isStreaming={isStreaming}
          isRegenUpdating={isRegenUpdating}
          isDesktop={isDesktop}
          preferenceCount={preferenceCount}
          timelineVariant={timelineVariant}
          timelineSectionRef={timelineSectionRef}
          savedTileIds={savedTileIds}
          handleOpenBookingDrawer={handleOpenBookingDrawer}
          onOpenStaysSettings={onOpenStaysSettings}
          onOpenFlightsSettings={onOpenFlightsSettings}
          fullModeMapItems={fullModeMapItems}
          mapCenter={mapCenter}
          hasDestinationCenter={destinationCenter !== null}
          fullModePOIs={fullModePOIs}
        />
        <BookingSummary
          tiles={effectiveTiles}
          dayCards={viewModel.day_cards ?? []}
          state={state}
          headerActions={venueLinksActions}
        />
        </div>

        <AnimatePresence>
          {showDesktopMap && (
            <motion.div key="desktop-map" initial={FADE_INITIAL} animate={FADE_VISIBLE}
              transition={MAP_TRANSITION} className="flex-1 min-w-[350px] self-stretch pt-10"
            >
              <div
                className="sticky top-0 relative overflow-hidden rounded-xl"
                style={{ height: `calc(100vh - ${headerOffset}px)` }}
              >
                <div className="absolute left-0 top-0 bottom-0 z-10 w-6 bg-gradient-to-r from-zinc-950/15 via-zinc-950/5 to-transparent pointer-events-none dark:from-zinc-950/35 dark:via-zinc-950/10" />
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
