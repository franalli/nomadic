'use client';

import type { RefObject } from 'react';
import { useMemo } from 'react';

import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import type { PlanResultPayload } from '@/components/layout/hooks/useBranchManager';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { formatDateForDisplay } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { PlanState, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

export interface UsePlannerContentArgs {
  chatPanelRef: RefObject<ChatPanelHandle | null>;
  chatKey: number;
  selectedBranchId: string | null;
  handlePlanResultWithReceipt: (result: PlanResultPayload) => void;
  handleGeneratePlanStartWithSnapshot: () => void;
  requestAutoExpandItinerary: () => void;
  hasBranchesReady: boolean;
  readyToGenerate: boolean;
  isGenerating: boolean;
  planState: PlanState;
  handleUserMessageSubmit: (message: string) => void;
  tripInputs: DocumentTripInputs;
  hasStartDate: boolean;
  hasEndDate: boolean;
  hasDestination: boolean;
  hasDates: boolean;
  bookingTypes: DocumentTripInputs['booking_types'];
  flightSettings: DocumentTripInputs['flight_settings'];
  hotelSettings: DocumentTripInputs['hotel_settings'];
  activitySettings: DocumentTripInputs['activity_settings'];
  handleUpdateBookingTypes: (
    bookingTypes: Partial<NonNullable<DocumentTripInputs['booking_types']>>
  ) => void;
  handleUpdateFlightSettings: (
    settings: Partial<NonNullable<DocumentTripInputs['flight_settings']>>
  ) => void;
  handleUpdateHotelSettings: (
    settings: Partial<NonNullable<DocumentTripInputs['hotel_settings']>>
  ) => void;
  handleUpdateActivitySettings: (
    settings: Partial<NonNullable<DocumentTripInputs['activity_settings']>>
  ) => void;
  planViewState: PlanViewState | null;
  isFraming: boolean;
  openSheet: (name: SheetType) => void;
  destinationImageUrl: string | null;
  handleStartNewSession: () => void | Promise<void>;
  destinationCard: { image_url?: string } | undefined;
}

export function usePlannerContent({
  chatPanelRef,
  chatKey,
  selectedBranchId,
  handlePlanResultWithReceipt,
  handleGeneratePlanStartWithSnapshot,
  requestAutoExpandItinerary,
  hasBranchesReady,
  readyToGenerate,
  isGenerating,
  planState,
  handleUserMessageSubmit,
  tripInputs,
  hasStartDate,
  hasEndDate,
  hasDestination,
  hasDates,
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  handleUpdateBookingTypes,
  handleUpdateFlightSettings,
  handleUpdateHotelSettings,
  handleUpdateActivitySettings,
  planViewState,
  isFraming,
  openSheet,
  destinationImageUrl,
  handleStartNewSession,
  destinationCard,
}: UsePlannerContentArgs) {
  return useMemo(
    () => (
      <ErrorBoundary label="Chat">
        <ChatPanel
          ref={chatPanelRef}
          key={chatKey}
          selectedBranchId={selectedBranchId}
          onPlanResult={handlePlanResultWithReceipt}
          onGeneratePlanStart={handleGeneratePlanStartWithSnapshot}
          onAutoExpandItinerary={requestAutoExpandItinerary}
          fullHeight={false}
          hasBranches={hasBranchesReady}
          readyToGenerate={readyToGenerate}
          isGenerating={isGenerating}
          planState={planState}
          onUserMessageSubmit={handleUserMessageSubmit}
          destination={tripInputs.destination ?? undefined}
          origin={tripInputs.origin ?? undefined}
          dateRange={
            hasStartDate && hasEndDate
              ? `${formatDateForDisplay(tripInputs.start_date)} - ${formatDateForDisplay(tripInputs.end_date)}`
              : hasStartDate
                ? `${formatDateForDisplay(tripInputs.start_date)} → ?`
                : undefined
          }
          budget={tripInputs.budget != null ? `$${tripInputs.budget.toLocaleString()}` : undefined}
          hasDestination={hasDestination}
          hasDates={hasDates}
          tripInputs={tripInputs}
          bookingTypes={bookingTypes}
          flightSettings={flightSettings}
          hotelSettings={hotelSettings}
          activitySettings={activitySettings}
          onUpdateBookingTypes={handleUpdateBookingTypes}
          onUpdateFlightSettings={handleUpdateFlightSettings}
          onUpdateHotelSettings={handleUpdateHotelSettings}
          onUpdateActivitySettings={handleUpdateActivitySettings}
          planViewState={planViewState ?? undefined}
          isFraming={isFraming}
          onOpenSheet={openSheet}
          destinationImageUrl={destinationCard?.image_url ?? destinationImageUrl}
          onConfirmReset={handleStartNewSession}
        />
      </ErrorBoundary>
    ),
    [
      activitySettings,
      bookingTypes,
      chatKey,
      chatPanelRef,
      destinationCard,
      destinationImageUrl,
      flightSettings,
      handleGeneratePlanStartWithSnapshot,
      handlePlanResultWithReceipt,
      handleStartNewSession,
      handleUpdateActivitySettings,
      handleUpdateBookingTypes,
      handleUpdateFlightSettings,
      handleUpdateHotelSettings,
      handleUserMessageSubmit,
      hasBranchesReady,
      hasDates,
      hasDestination,
      hasEndDate,
      hasStartDate,
      hotelSettings,
      isFraming,
      isGenerating,
      openSheet,
      planState,
      planViewState,
      readyToGenerate,
      requestAutoExpandItinerary,
      selectedBranchId,
      tripInputs,
    ]
  );
}
