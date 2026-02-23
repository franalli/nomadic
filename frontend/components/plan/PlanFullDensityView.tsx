'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Building2, ChevronDown, Compass, Lightbulb, Plane } from 'lucide-react';
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
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel, PlanViewState, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { BookingSection } from './BookingSection';
import { OriginPromptCard } from './OriginPromptCard';
import type { GenerationState } from './planStateHelpers';
import { PlanTimelineSection } from './PlanTimelineSection';
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
  const [staysExpanded, setStaysExpanded] = useState(false);
  const [flightsExpanded, setFlightsExpanded] = useState(false);
  const onToggleStays = useCallback(() => setStaysExpanded((v) => !v), []);
  const onToggleFlights = useCallback(() => setFlightsExpanded((v) => !v), []);

  const [intelExpanded, setIntelExpanded] = useState(false);
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
  const { categories: intelCategories } = useMemo(
    () => buildDestinationIntel(effectiveStrategySections),
    [effectiveStrategySections]
  );
  const effectiveLocalExpertSection = useMemo(
    () => effectiveStrategySections.find((s) => s.specialist_type === 'local_expert'),
    [effectiveStrategySections]
  );
  const isTravelIntelPending = localExpertEnrichmentState(effectiveLocalExpertSection) === 'pending';
  const hasDestinationIntel = intelCategories.length > 0;
  const travelIntelSectionCount = intelCategories.length;
  const travelAdviceLabel = isTravelIntelPending
    ? 'Travel Advice'
    : `Travel Advice (${travelIntelSectionCount})`;
  const showRowTwoChips = hasDestinationIntel || (hasItineraryContent && (flightCount > 0 || stayCount > 0));

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

      while (!cancelled) {
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
        if (cancelled) return;
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

  const subduedTogglePillClass = cn(
    'inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-sm whitespace-nowrap transition-colors',
    'border-zinc-300 dark:border-white/15 bg-zinc-100 dark:bg-white/[0.06]',
    'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-white/10',
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

        {/* Row 2 chips — Flights/Stays + destination intel */}
        {showRowTwoChips && (
          <div className="px-4 pb-2 pt-1">
            <div className="flex items-center gap-2">
              {flightCount > 0 && (
                <button
                  type="button"
                  onClick={onToggleFlights}
                  className={subduedTogglePillClass}
                >
                  <Plane className="w-3 h-3 shrink-0" />
                  Flights ({flightCount})
                  <ChevronDown className={cn('w-3 h-3 transition-transform', flightsExpanded && 'rotate-180')} />
                </button>
              )}
              {stayCount > 0 && (
                <button
                  type="button"
                  onClick={onToggleStays}
                  className={subduedTogglePillClass}
                >
                  <Building2 className="w-3 h-3 shrink-0" />
                  Stays ({stayCount})
                  <ChevronDown className={cn('w-3 h-3 transition-transform', staysExpanded && 'rotate-180')} />
                </button>
              )}
              {hasDestinationIntel && (
                <button
                  id="destination-intel-trigger"
                  type="button"
                  aria-expanded={intelExpanded}
                  aria-controls="destination-intel-panel"
                  aria-busy={isAnyRegenerating || isTravelIntelPending ? true : undefined}
                  onClick={() => setIntelExpanded(v => !v)}
                  className={cn(
                    subduedTogglePillClass,
                    'max-w-[360px] justify-between',
                    isAnyRegenerating && 'opacity-70'
                  )}
                >
                  <span className="flex items-center gap-1.5 min-w-0">
                    <Lightbulb className="w-3 h-3 shrink-0" />
                    <span className="truncate">{travelAdviceLabel}</span>
                  </span>
                  <span className="flex items-center gap-1 shrink-0">
                    {isTravelIntelPending && (
                      <Compass
                        className="w-3 h-3 compass-spin text-emerald-500"
                        aria-label="Travel advice is loading"
                      />
                    )}
                    <ChevronDown className={cn('w-3 h-3 transition-transform', intelExpanded && 'rotate-180')} />
                  </span>
                </button>
              )}
            </div>

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

            {hasDestinationIntel && isAnyRegenerating && (
              <div className="mt-2 flex items-center gap-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-zinc-900/60 px-3 py-2">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
                <p className="text-xs text-zinc-600 dark:text-zinc-400">
                  {isRegenUpdating ? 'Updating itinerary...' : 'Updating plan...'}
                </p>
              </div>
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
