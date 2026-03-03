'use client';

import { AnimatePresence, motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { useMapSync } from '@/hooks/useMapSync';
import { REVEAL_TIMING } from '@/lib/animation-config';
import { getSpecialistEnrichment } from '@/lib/api';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import { calculateMapCenter, extractPOIsFromSections } from '@/lib/ghost-timeline-adapter';
import { buildDestinationIntel } from '@/lib/travelIntel';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel, PlanViewState, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { BookingSummary } from './BookingSummary';
import { FullDensityTimeline } from './FullDensityTimeline';
import type { GenerationState } from './planStateHelpers';
import { type TimelineVariant } from './TimelineThread';

const DESKTOP_MAP_CONTENT_STYLE = { minWidth: 480, maxWidth: 800 } as const;
const DESTINATION_INTEL_CACHE = new Map<string, StrategySection>();
const DESTINATION_INTEL_INFLIGHT = new Map<string, Promise<void>>();

function normalizeDestinationKey(destination: string | null | undefined): string {
  return (destination || '').trim().toLowerCase();
}

function hasTravelIntelligence(section: StrategySection | undefined): boolean {
  return Boolean(section?.travel_intelligence && Object.keys(section.travel_intelligence).length > 0);
}

function localExpertEnrichmentState(section: StrategySection | undefined): string {
  const raw = section?.local_expert_enrichment?.state;
  if (typeof raw !== 'string') return '';
  return raw.trim().toLowerCase();
}

function sectionFingerprint(section: StrategySection | null | undefined): string {
  if (!section) return '';
  const enrichment = section.local_expert_enrichment;
  const updatedAt = typeof enrichment?.updated_at === 'string' ? enrichment.updated_at : '';
  const enrichmentState = typeof enrichment?.state === 'string' ? enrichment.state : '';
  return [
    section.id ?? '',
    enrichmentState,
    updatedAt,
    section.constraints_applied?.length ?? 0,
    section.content_added?.length ?? 0,
    section.travel_intelligence ? Object.keys(section.travel_intelligence).length : 0,
  ].join('|');
}
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
}

export function PlanFullDensityView({
  state, viewModel, fullModeSections, fullModePOIs,
  effectiveTiles, effectiveTripInputs, destinationCard, generation,
  savedTileIds, hasSectionData, hasItineraryContent, isExpandingItinerary,
  isStreaming, isAnyRegenerating, isRegenUpdating, isDesktop,
  preferenceCount, effectiveMode, timelineVariant,
  timelineSectionRef, scrollContainerRef, handleSaveTile, handleOpenBookingDrawer,
  onOpenStaysSettings, onOpenFlightsSettings,
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
  const [staysExpanded, setStaysExpanded] = useState(false);
  const [flightsExpanded, setFlightsExpanded] = useState(false);
  const onToggleStays = useCallback(() => setStaysExpanded((v) => !v), []);
  const onToggleFlights = useCallback(() => setFlightsExpanded((v) => !v), []);

  const intelDestinationKey = normalizeDestinationKey(effectiveFullDest);
  const localExpertSection = useMemo(
    () => strategySections.find((s) => s.specialist_type === 'local_expert'),
    [strategySections]
  );
  const localExpertSectionId = localExpertSection?.id ?? null;
  const localExpertHasTI = hasTravelIntelligence(localExpertSection);
  const localExpertSectionEnrichment = localExpertEnrichmentState(localExpertSection);
  const localExpertReady = localExpertSectionEnrichment === 'ready';
  const localExpertSectionRef = useRef<StrategySection | null>(null);
  // Track streaming state in a ref so the enrichment polling loop can
  // bail out when a new graph request starts (props are stale in closures).
  const isStreamingRef = useRef(isStreaming);
  // Monotonic turn counter — increments each time streaming starts.
  // Polling loops capture the value at start and bail if it changes,
  // closing the 0-500ms race window between "user sends" and "first SSE event".
  const turnCounterRef = useRef(0);
  useEffect(() => {
    isStreamingRef.current = isStreaming;
    if (isStreaming) turnCounterRef.current += 1;
  }, [isStreaming]);
  const [enrichedLocalExpertSection, setEnrichedLocalExpertSection] = useState<StrategySection | null>(null);
  const effectiveStrategySections = useMemo(() => {
    if (!localExpertSectionId || !enrichedLocalExpertSection) {
      return strategySections;
    }
    return strategySections.map((section) => {
      if (section.id !== localExpertSectionId) return section;
      return { ...section, ...enrichedLocalExpertSection };
    });
  }, [enrichedLocalExpertSection, localExpertSectionId, strategySections]);
  const { categories: intelCategories, tipCount: travelIntelItemCount } = useMemo(
    () => buildDestinationIntel(effectiveStrategySections),
    [effectiveStrategySections]
  );
  const effectiveLocalExpertSection = useMemo(
    () => effectiveStrategySections.find((s) => s.specialist_type === 'local_expert'),
    [effectiveStrategySections]
  );
  const isTravelIntelPending = localExpertEnrichmentState(effectiveLocalExpertSection) === 'pending';
  const hasDestinationIntel = intelCategories.length > 0;
  const travelAdviceLabel = isTravelIntelPending
    ? 'Travel Advice'
    : `Travel Advice (${travelIntelItemCount})`;
  useEffect(() => {
    setEnrichedLocalExpertSection(null);
  }, [intelDestinationKey, localExpertSectionId]);

  useEffect(() => {
    localExpertSectionRef.current = localExpertSection ?? null;
  }, [localExpertSection]);

  useEffect(() => {
    if (!localExpertSectionId || !intelDestinationKey) return;
    let cancelled = false;

    const applySectionUpdate = (enriched: StrategySection) => {
      if (cancelled) return;
      setEnrichedLocalExpertSection((current) => (
        sectionFingerprint(current) === sectionFingerprint(enriched) ? current : enriched
      ));
    };

    const sourceSection = localExpertSectionRef.current;
    if (localExpertReady && localExpertHasTI && sourceSection) {
      DESTINATION_INTEL_CACHE.set(intelDestinationKey, sourceSection);
      applySectionUpdate(sourceSection);
      return () => {
        cancelled = true;
      };
    }

    const cached = DESTINATION_INTEL_CACHE.get(intelDestinationKey);
    if (cached) {
      applySectionUpdate(cached);
      return () => {
        cancelled = true;
      };
    }

    const run = async () => {
      const maxPendingMs = 75_000;
      const startedAt = Date.now();
      let pendingAttempts = 0;
      let transientErrors = 0;
      const startTurn = turnCounterRef.current;

      // Initial delay: Phase B LLM enrichment takes 10-20s, skip wasted early polls
      await new Promise((resolve) => setTimeout(resolve, 3000));
      if (cancelled) return;

      while (!cancelled) {
        // Abandon polling when a new graph request starts — fresh
        // enrichment data will arrive with the new response.
        if (isStreamingRef.current || turnCounterRef.current !== startTurn) return;

        let result: Awaited<ReturnType<typeof getSpecialistEnrichment>> = null;
        try {
          result = await getSpecialistEnrichment(localExpertSectionId);
        } catch {
          if (cancelled) return;
          transientErrors += 1;
          if (transientErrors >= 3) return;
          await new Promise((resolve) => setTimeout(resolve, 2000));
          continue;
        }
        if (cancelled || isStreamingRef.current || turnCounterRef.current !== startTurn) return;
        transientErrors = 0;
        if (!result) return;

        if (result.status === 'ready' && result.data) {
          const enriched = result.data as unknown as StrategySection;
          DESTINATION_INTEL_CACHE.set(intelDestinationKey, enriched);
          applySectionUpdate(enriched);
          return;
        }

        if (result.status === 'failed') return;
        if (Date.now() - startedAt >= maxPendingMs) return;

        pendingAttempts += 1;
        const suggestedWait = result.retry_after_ms ?? 1500;
        const waitMs = Math.max(1500, Math.min(suggestedWait + pendingAttempts * 150, 5000));
        await new Promise((resolve) => setTimeout(resolve, waitMs));
      }
    };

    const startPolling = (): Promise<void> => {
      const inflight = run().finally(() => {
        DESTINATION_INTEL_INFLIGHT.delete(intelDestinationKey);
      });
      DESTINATION_INTEL_INFLIGHT.set(intelDestinationKey, inflight);
      return inflight;
    };

    const existingInflight = DESTINATION_INTEL_INFLIGHT.get(intelDestinationKey);
    if (existingInflight) {
      void existingInflight.finally(() => {
        if (cancelled) return;
        const fromCache = DESTINATION_INTEL_CACHE.get(intelDestinationKey);
        if (fromCache) {
          applySectionUpdate(fromCache);
          return;
        }
        // If an older in-flight poll completed without populating cache
        // (e.g. cancelled during StrictMode remount), kick off one fresh poll.
        if (!DESTINATION_INTEL_INFLIGHT.has(intelDestinationKey)) {
          void startPolling();
        }
      });
      return () => {
        cancelled = true;
      };
    }

    void startPolling();

    return () => {
      cancelled = true;
    };
  }, [
    intelDestinationKey,
    localExpertHasTI,
    localExpertReady,
    localExpertSectionId,
  ]);

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

  }, [hasItineraryContent, staysExpanded, flightsExpanded, stayCount, flightCount, showDesktopMap, scrollContainerRef, timelineSectionRef]);

  return (
    <div className="flex flex-col">
      {/* Content + map — side by side, map top-aligned with Day 1 */}
      <div ref={flexRowRef} className={cn('flex', showDesktopMap && 'gap-6')}>
        <div
          ref={contentColRef}
          className={cn('flex flex-col min-w-0', showDesktopMap ? 'flex-1' : 'w-full')}
          style={showDesktopMap ? DESKTOP_MAP_CONTENT_STYLE : undefined}
        >
        <FullDensityTimeline
          state={state}
          viewModel={viewModel}
          effectiveStrategySections={effectiveStrategySections}
          effectiveTiles={effectiveTiles}
          effectiveTripInputs={effectiveTripInputs}
          generation={generation}
          savedTileIds={savedTileIds}
          hasSectionData={hasSectionData}
          hasItineraryContent={hasItineraryContent}
          isExpandingItinerary={isExpandingItinerary}
          isStreaming={isStreaming}
          isAnyRegenerating={isAnyRegenerating}
          isRegenUpdating={isRegenUpdating}
          isDesktop={isDesktop}
          preferenceCount={preferenceCount}
          effectiveMode={effectiveMode}
          timelineVariant={timelineVariant}
          timelineSectionRef={timelineSectionRef}
          handleSaveTile={handleSaveTile}
          handleOpenBookingDrawer={handleOpenBookingDrawer}
          onOpenStaysSettings={onOpenStaysSettings}
          onOpenFlightsSettings={onOpenFlightsSettings}
          fullModeMapItems={fullModeMapItems}
          mapCenter={mapCenter}
          hasDestinationCenter={destinationCenter !== null}
          fullModePOIs={fullModePOIs}
          stayCount={stayCount}
          flightCount={flightCount}
          staysExpanded={staysExpanded}
          flightsExpanded={flightsExpanded}
          onToggleStays={onToggleStays}
          onToggleFlights={onToggleFlights}
          intelCategories={intelCategories}
          hasDestinationIntel={hasDestinationIntel}
          isTravelIntelPending={isTravelIntelPending}
          travelAdviceLabel={travelAdviceLabel}
        />
        <BookingSummary
          tiles={effectiveTiles}
          dayCards={viewModel.day_cards ?? []}
          state={state}
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
