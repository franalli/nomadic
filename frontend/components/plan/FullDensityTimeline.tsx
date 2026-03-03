'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { Building2, Compass, Lightbulb, Plane } from 'lucide-react';
import type { ReactNode } from 'react';
import { useState } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { REVEAL_TIMING } from '@/lib/animation-config';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import { buildDestinationIntel } from '@/lib/travelIntel';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { PlanViewModel, PlanViewState, StrategySection } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { BookingSection } from './BookingSection';
import { OriginPromptCard } from './OriginPromptCard';
import { PdfExportButton } from './PdfExportButton';
import type { GenerationState } from './planStateHelpers';
import { PlanTimelineSection } from './PlanTimelineSection';
import type { TimelineVariant } from './TimelineThread';

// =============================================================================
// Types
// =============================================================================

export interface FullDensityTimelineProps {
  state: PlanViewState;
  viewModel: PlanViewModel;
  effectiveStrategySections: StrategySection[];
  effectiveTiles: Record<string, Tile>;
  effectiveTripInputs: DocumentTripInputs | undefined;
  generation?: GenerationState | null;
  savedTileIds: Set<string>;
  hasSectionData: boolean;
  hasItineraryContent: boolean;
  isExpandingItinerary: boolean;
  isStreaming: boolean;
  isAnyRegenerating: boolean;
  isRegenUpdating: boolean;
  isDesktop: boolean;
  preferenceCount: number;
  effectiveMode: string;
  timelineVariant: TimelineVariant;
  timelineSectionRef: React.RefObject<HTMLDivElement | null>;
  handleSaveTile: (tile: Tile) => Promise<void>;
  handleOpenBookingDrawer: (category: 'hotel' | 'flight' | 'activity', dayNumber?: number) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
  /** Map items for mobile map */
  fullModeMapItems: MapPOI[];
  /** Center coordinates for map */
  mapCenter: { lat: number; lng: number; zoom: number };
  /** Whether a destination center is available from hotel tiles */
  hasDestinationCenter: boolean;
  /** Full-mode POIs from day cards */
  fullModePOIs: MapPOI[];
  /** Booking chip state */
  stayCount: number;
  flightCount: number;
  staysExpanded: boolean;
  flightsExpanded: boolean;
  onToggleStays: () => void;
  onToggleFlights: () => void;
  /** Intel state */
  intelCategories: ReturnType<typeof buildDestinationIntel>['categories'];
  hasDestinationIntel: boolean;
  isTravelIntelPending: boolean;
  travelAdviceLabel: string;
  travelAdviceCount: number;
  /** Handler to open trip-input sheets (passed to TripSummaryPills) */
  onOpenSheet?: (sheet: SheetType) => void;
}

// =============================================================================
// Component
// =============================================================================

export function FullDensityTimeline({
  state,
  viewModel,
  effectiveStrategySections,
  effectiveTiles,
  effectiveTripInputs,
  generation,
  savedTileIds,
  hasSectionData,
  hasItineraryContent,
  isExpandingItinerary,
  isStreaming,
  isAnyRegenerating,
  isRegenUpdating,
  isDesktop,
  preferenceCount,
  effectiveMode,
  timelineVariant,
  timelineSectionRef,
  handleSaveTile,
  handleOpenBookingDrawer,
  onOpenStaysSettings,
  onOpenFlightsSettings,
  fullModeMapItems,
  mapCenter,
  hasDestinationCenter,
  fullModePOIs,
  stayCount,
  flightCount,
  staysExpanded,
  flightsExpanded,
  onToggleStays,
  onToggleFlights,
  intelCategories,
  hasDestinationIntel,
  isTravelIntelPending,
  travelAdviceLabel,
  travelAdviceCount,
  onOpenSheet,
}: FullDensityTimelineProps): ReactNode {
  const [intelExpanded, setIntelExpanded] = useState(false);

  const showRowTwoChips = hasDestinationIntel || hasItineraryContent;

  const subduedTogglePillClass = cn(
    'inline-flex h-8 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold whitespace-nowrap transition-colors',
    'border-zinc-300 dark:border-white/15 bg-zinc-100 dark:bg-white/[0.06]',
    'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-white/10',
  );

  return (
    <>
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

      {/* Unified chip row — trip summary pills + row 2 chips */}
      <div className="px-4 pb-2 pt-3">
        {effectiveTripInputs && onOpenSheet ? (
          <TripSummaryPills
            tripInputs={effectiveTripInputs}
            dayCards={viewModel.day_cards}
            onOpenSheet={onOpenSheet}
            disabled={isStreaming}
          >
            {showRowTwoChips && (
              <>
                <div className="h-5 w-px bg-zinc-300 dark:bg-white/15 mx-1" />
                {flightCount > 0 && (
                  <button
                    type="button"
                    onClick={onToggleFlights}
                    className={cn(subduedTogglePillClass, 'relative')}
                  >
                    <Plane className="w-3 h-3 shrink-0" />
                    Flights
                    <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-white text-zinc-900 text-[11px] font-bold shadow-sm dark:bg-zinc-100 dark:text-zinc-900">
                      {flightCount}
                    </span>
                  </button>
                )}
                {stayCount > 0 && (
                  <button
                    type="button"
                    onClick={onToggleStays}
                    className={cn(subduedTogglePillClass, 'relative')}
                  >
                    <Building2 className="w-3 h-3 shrink-0" />
                    Stays
                    <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-white text-zinc-900 text-[11px] font-bold shadow-sm dark:bg-zinc-100 dark:text-zinc-900">
                      {stayCount}
                    </span>
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
                      'relative max-w-[360px] justify-between',
                      isAnyRegenerating && 'opacity-70'
                    )}
                  >
                    <span className="flex items-center gap-1.5 min-w-0">
                      <Lightbulb className="w-3 h-3 shrink-0" />
                      <span className="truncate">{travelAdviceLabel}</span>
                    </span>
                    {isTravelIntelPending && (
                      <Compass
                        className="w-3 h-3 compass-spin text-emerald-500"
                        aria-label="Travel advice is loading"
                      />
                    )}
                    {travelAdviceCount > 0 && !isTravelIntelPending && (
                      <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-white text-zinc-900 text-[11px] font-bold shadow-sm dark:bg-zinc-100 dark:text-zinc-900">
                        {travelAdviceCount}
                      </span>
                    )}
                  </button>
                )}
                <PdfExportButton
                  tripInputs={effectiveTripInputs}
                  dayCards={viewModel.day_cards ?? []}
                  tiles={effectiveTiles}
                />
              </>
            )}
          </TripSummaryPills>
        ) : showRowTwoChips ? (
          <div className="flex items-center gap-2 relative z-10">
            {flightCount > 0 && (
              <button
                type="button"
                onClick={onToggleFlights}
                className={cn(subduedTogglePillClass, 'relative')}
              >
                <Plane className="w-3 h-3 shrink-0" />
                Flights
                <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-white text-zinc-900 text-[11px] font-bold shadow-sm dark:bg-zinc-100 dark:text-zinc-900">
                  {flightCount}
                </span>
              </button>
            )}
            {stayCount > 0 && (
              <button
                type="button"
                onClick={onToggleStays}
                className={cn(subduedTogglePillClass, 'relative')}
              >
                <Building2 className="w-3 h-3 shrink-0" />
                Stays
                <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-white text-zinc-900 text-[11px] font-bold shadow-sm dark:bg-zinc-100 dark:text-zinc-900">
                  {stayCount}
                </span>
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
                  'relative max-w-[360px] justify-between',
                  isAnyRegenerating && 'opacity-70'
                )}
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  <Lightbulb className="w-3 h-3 shrink-0" />
                  <span className="truncate">{travelAdviceLabel}</span>
                </span>
                {isTravelIntelPending && (
                  <Compass
                    className="w-3 h-3 compass-spin text-emerald-500"
                    aria-label="Travel advice is loading"
                  />
                )}
                {travelAdviceCount > 0 && !isTravelIntelPending && (
                  <span className="absolute -top-1.5 -right-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-white text-zinc-900 text-[11px] font-bold shadow-sm dark:bg-zinc-100 dark:text-zinc-900">
                    {travelAdviceCount}
                  </span>
                )}
              </button>
            )}
            <PdfExportButton
              tripInputs={effectiveTripInputs}
              dayCards={viewModel.day_cards ?? []}
              tiles={effectiveTiles}
            />
          </div>
        ) : null}

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

      {!isDesktop && hasItineraryContent && (fullModePOIs.length > 0 || hasDestinationCenter) && (
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
    </>
  );
}
