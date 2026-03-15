'use client';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import type { DocumentTripInputs } from '@/types/document';
import type { PlanViewModel } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface PlanFullDensityMobileSummaryProps {
  isDesktop: boolean;
  effectiveTripInputs: DocumentTripInputs | undefined;
  onOpenSheet?: (sheet: SheetType) => void;
  isStreaming: boolean;
  hasItineraryContent: boolean;
  flightCount: number;
  stayCount: number;
  travelIntelItemCount: number;
  showTravelAdviceSegment: boolean;
  isTravelIntelPending: boolean;
  flightsExpanded: boolean;
  staysExpanded: boolean;
  intelExpanded: boolean;
  onToggleFlights: () => void;
  onToggleStays: () => void;
  onToggleIntel: () => void;
  dayCards: PlanViewModel['day_cards'];
}

export function PlanFullDensityMobileSummary({
  isDesktop,
  effectiveTripInputs,
  onOpenSheet,
  isStreaming,
  hasItineraryContent,
  flightCount,
  stayCount,
  travelIntelItemCount,
  showTravelAdviceSegment,
  isTravelIntelPending,
  flightsExpanded,
  staysExpanded,
  intelExpanded,
  onToggleFlights,
  onToggleStays,
  onToggleIntel,
  dayCards,
}: PlanFullDensityMobileSummaryProps) {
  if (isDesktop || !effectiveTripInputs || !onOpenSheet) return null;

  return (
    <div className="px-4 pb-2 pt-1">
      <TripSummaryPills
        tripInputs={effectiveTripInputs}
        dayCards={dayCards}
        onOpenSheet={onOpenSheet}
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
  );
}
