'use client';

import type { ReactNode } from 'react';

import { InteractiveMap } from '@/components/map/InteractiveMap';
import { MapErrorBoundary } from '@/components/map/MapErrorBoundary';
import type { MapPOI } from '@/lib/ghost-timeline-adapter';
import type { PlanViewModel } from '@/types/plan-envelope';

import { PlanTimelineSection } from './PlanTimelineSection';
import type { TimelineVariant } from './TimelineThread';

// =============================================================================
// Types
// =============================================================================

export interface FullDensityTimelineProps {
  viewModel: PlanViewModel;
  hasItineraryContent: boolean;
  isExpandingItinerary: boolean;
  isStreaming: boolean;
  isRegenUpdating: boolean;
  isDesktop: boolean;
  preferenceCount: number;
  timelineVariant: TimelineVariant;
  timelineSectionRef: React.RefObject<HTMLDivElement | null>;
  savedTileIds: Set<string>;
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
}

// =============================================================================
// Component
// =============================================================================

export function FullDensityTimeline({
  viewModel,
  hasItineraryContent,
  isExpandingItinerary,
  isStreaming,
  isRegenUpdating,
  isDesktop,
  preferenceCount,
  timelineVariant,
  timelineSectionRef,
  savedTileIds,
  handleOpenBookingDrawer,
  onOpenStaysSettings,
  onOpenFlightsSettings,
  fullModeMapItems,
  mapCenter,
  hasDestinationCenter,
  fullModePOIs,
}: FullDensityTimelineProps): ReactNode {
  return (
    <>
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
        dayCards={viewModel.day_cards ?? []}
        timelineVariant={timelineVariant}
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
