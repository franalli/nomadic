'use client';

/**
 * PlanDensityViews — Ghost, bridge, and mirror-loader density views.
 * @see docs/ux_unified_architecture.md Section VII - Data Density Levels
 */

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import { DS } from '@/lib/design-system';
import { calculateMapCenter, extractPOIsFromSections } from '@/lib/ghost-timeline-adapter';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DestinationCard, PlanViewModel } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

import { DestinationIntelCard } from './DestinationIntelCard';
import { DestinationMapPlaceholder } from './DestinationMapPlaceholder';
import { TimelineSkeleton } from './timeline/TimelineSkeleton';
import { TimelineThread } from './TimelineThread';

export function PlanMirrorLoader({ tripDuration }: { tripDuration: number }) {
  return (
    <div className="p-4 space-y-6">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
        <span className="text-sm text-zinc-500 dark:text-zinc-400">Searching live availability...</span>
      </div>
      <TimelineSkeleton />
      <p className="text-xs text-zinc-500 dark:text-zinc-400 text-center">
        Finding flights and hotels for your {tripDuration}-day trip
      </p>
    </div>
  );
}

interface GhostDensityViewProps {
  filteredViewModel: PlanViewModel;
  totalConstraints: number;
  ghostDayCards: PlanViewModel['day_cards'];
  ghostHasDuration: boolean;
  effectiveTripInputs: DocumentTripInputs | undefined;
  onSelectNights?: (nights: number) => void;
  onOpenSheet?: (sheet: SheetType) => void;
  onOpenStaysSettings?: () => void;
  onOpenFlightsSettings?: () => void;
}

export function PlanGhostDensityView({
  filteredViewModel,
  totalConstraints,
  ghostDayCards,
  ghostHasDuration,
  effectiveTripInputs,
  onSelectNights,
  onOpenSheet,
  onOpenStaysSettings,
  onOpenFlightsSettings,
}: GhostDensityViewProps) {
  const destination = effectiveTripInputs?.destination;
  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">⚡</span>
          <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
            Planning Intelligence
          </h3>
        </div>
        {totalConstraints > 0 && (
          <span className={`${DS.textSize.micro} px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium`}>
            {totalConstraints} constraint{totalConstraints > 1 ? 's' : ''} applied
          </span>
        )}
      </div>
      <DestinationIntelCard destination={destination} sections={filteredViewModel.strategy_sections ?? []} />
      <TimelineThread
        dayCards={ghostDayCards ?? []}
        isDraft={true}
        showPriceEstimates={false}
        hasDuration={ghostHasDuration}
        startDate={effectiveTripInputs?.start_date ?? null}
        onSelectNights={onSelectNights}
        onOpenDatePicker={() => onOpenSheet?.('dates')}
        onOpenStaysSettings={onOpenStaysSettings}
        onOpenFlightsSettings={onOpenFlightsSettings}
      />
      <div className="text-center pt-4 pb-6">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Tips and constraints are in place. Add dates to generate your itinerary.
        </p>
      </div>
    </div>
  );
}

interface BridgeDensityViewProps {
  filteredViewModel: PlanViewModel;
  totalConstraints: number;
  hasDates: boolean;
  destinationCard?: DestinationCard;
  effectiveTripInputs: DocumentTripInputs | undefined;
}

export function PlanBridgeDensityView({
  filteredViewModel,
  totalConstraints,
  hasDates,
  destinationCard,
  effectiveTripInputs,
}: BridgeDensityViewProps) {
  const sections = filteredViewModel.strategy_sections ?? [];
  const effectiveDestination = effectiveTripInputs?.destination ?? destinationCard?.title;
  const mapPOIs = extractPOIsFromSections(sections, effectiveDestination);
  const bridgeMapCenter =
    mapPOIs.length > 0 ? calculateMapCenter(mapPOIs) : { lat: 20, lng: 0, zoom: 2 };

  return (
    <div className="flex flex-col lg:flex-row gap-6 p-4">
      <div className="flex-1 min-w-0 space-y-4">
        {!hasDates && (
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">⚡</span>
              <h3 className="text-xs font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                Planning Intelligence
              </h3>
            </div>
            {totalConstraints > 0 && (
              <span className={`${DS.textSize.micro} px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-medium`}>
                {totalConstraints} constraint{totalConstraints > 1 ? 's' : ''} applied
              </span>
            )}
          </div>
        )}
        <DestinationIntelCard
          destination={effectiveDestination}
          sections={filteredViewModel.strategy_sections ?? []}
        />
      </div>
      <div className={cn('hidden w-[350px] shrink-0 lg:block')}>
        <div className="sticky top-4 h-[400px] overflow-hidden rounded-xl">
          {mapPOIs.length > 0 ? (
            <MapErrorBoundary className="h-full w-full">
              <InteractiveMap
                items={mapPOIs}
                activeItemId={null}
                defaultCenter={bridgeMapCenter}
                className="h-full w-full"
              />
            </MapErrorBoundary>
          ) : (
            <DestinationMapPlaceholder
              destination={destinationCard?.title || 'Destination'}
              imageUrl={destinationCard?.image_url || ''}
              className="h-full"
            />
          )}
        </div>
      </div>
    </div>
  );
}
