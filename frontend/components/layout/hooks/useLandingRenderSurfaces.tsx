'use client';

import type { RefObject } from 'react';
import { useMemo } from 'react';

import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { MobileChatInput } from '@/components/chat/MobileChatInput';
import type { PlanResultPayload } from '@/components/layout/hooks/useBranchManager';
import { LandingHeaderContent } from '@/components/layout/LandingHeaderContent';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { formatDateForDisplay } from '@/lib/utils';
import type { AuthUser, UserTripSummary } from '@/state/userStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { DestinationCard, PlanState, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

interface UseLandingRenderSurfacesArgs {
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
  destinationCard: DestinationCard | undefined;
  destinationImageUrl: string | null;
  handleStartNewSession: () => void | Promise<void>;
  generation: GenerationState | null;
  canGeneratePlan: boolean;
  fallbackTitle: string | undefined;
  handleBuildPlan: () => void;
  handleExpandToItinerary: () => Promise<void>;
  handleFinalizePlan: () => void;
  isFinalizing: boolean;
  preferredTileIds: Set<string>;
  handleSaveTilePreference: (tile: Tile) => void;
  isCommitting: boolean;
  hasEverHadPlan: boolean;
  isRegenerating: boolean;
  handleSelectNights: (nights: number) => void;
  handleOpenGearActivities: () => void;
  handleOpenGearStays: () => void;
  handleOpenGearFlights: () => void;
  planViewModel: PlanViewModel;
  tiles: Record<string, Tile>;
  hasItineraryContent: boolean;
  showHeaderPills: boolean;
  user: AuthUser | null;
  otherTrips: UserTripSummary[];
  resumingTripId: number | null;
  userLoading: boolean;
  handleNewTrip: () => Promise<void>;
  handleLogin: () => Promise<void>;
  handleLogout: () => Promise<void>;
  resumeTrip: (tripId: number) => Promise<boolean>;
  addToast: (message: string, type?: ToastType) => void;
  isResettingSession: boolean;
  isDesktop: boolean;
  handleMobileSend: (message: string) => void;
  handleMobileStopStreaming: () => void;
  hasPlan: boolean;
}

export function useLandingRenderSurfaces({
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
  destinationCard,
  destinationImageUrl,
  handleStartNewSession,
  generation,
  canGeneratePlan,
  fallbackTitle,
  handleBuildPlan,
  handleExpandToItinerary,
  handleFinalizePlan,
  isFinalizing,
  preferredTileIds,
  handleSaveTilePreference,
  isCommitting,
  hasEverHadPlan,
  isRegenerating,
  handleSelectNights,
  handleOpenGearActivities,
  handleOpenGearStays,
  handleOpenGearFlights,
  planViewModel,
  tiles,
  hasItineraryContent,
  showHeaderPills,
  user,
  otherTrips,
  resumingTripId,
  userLoading,
  handleNewTrip,
  handleLogin,
  handleLogout,
  resumeTrip,
  addToast,
  isResettingSession,
  isDesktop,
  handleMobileSend,
  handleMobileStopStreaming,
  hasPlan,
}: UseLandingRenderSurfacesArgs) {
  const plannerContent = useMemo(
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

  const isExpandingItinerary =
    generation?.active === true && generation.stage === 'itinerary';

  const planViewContent = useMemo(
    () => (
      <ErrorBoundary label="Plan View">
        <StrategyStageRenderer
          state={planViewState ?? 'P0_MINIMAL'}
          viewModel={planViewModel}
          destinationCard={destinationCard ?? undefined}
          tiles={tiles}
          generation={generation}
          canGeneratePlan={canGeneratePlan}
          fallbackTitle={fallbackTitle}
          hasDates={hasDates}
          isExpandingItinerary={isExpandingItinerary}
          onBuildPlan={handleBuildPlan}
          onExpandToItinerary={handleExpandToItinerary}
          onFinalizePlan={handleFinalizePlan}
          isFinalizing={isFinalizing}
          savedTileIds={preferredTileIds}
          onSaveTile={handleSaveTilePreference}
          tripInputs={tripInputs}
          isCommitting={isCommitting}
          onOpenSheet={openSheet}
          hasEverHadPlan={hasEverHadPlan}
          isRegenerating={isRegenerating}
          onSelectNights={handleSelectNights}
          onOpenActivitySettings={handleOpenGearActivities}
          onOpenStaysSettings={handleOpenGearStays}
          onOpenFlightsSettings={handleOpenGearFlights}
        />
      </ErrorBoundary>
    ),
    [
      canGeneratePlan,
      destinationCard,
      fallbackTitle,
      generation,
      handleBuildPlan,
      handleExpandToItinerary,
      handleFinalizePlan,
      handleOpenGearActivities,
      handleOpenGearFlights,
      handleOpenGearStays,
      handleSaveTilePreference,
      handleSelectNights,
      hasDates,
      hasEverHadPlan,
      isCommitting,
      isExpandingItinerary,
      isFinalizing,
      isRegenerating,
      openSheet,
      planViewModel,
      planViewState,
      preferredTileIds,
      tiles,
      tripInputs,
    ]
  );

  const headerContent = useMemo(
    () => (
      <LandingHeaderContent
        tiles={tiles}
        tripInputs={tripInputs}
        dayCards={planViewModel.day_cards}
        openSheet={openSheet}
        isGenerating={isGenerating}
        hasItineraryContent={hasItineraryContent}
        showHeaderPills={showHeaderPills}
        user={user}
        otherTrips={otherTrips}
        resumingTripId={resumingTripId}
        userLoading={userLoading}
        handleNewTrip={handleNewTrip}
        handleLogin={handleLogin}
        handleLogout={handleLogout}
        handleStartNewSession={handleStartNewSession}
        resumeTrip={resumeTrip}
        addToast={addToast}
        isResettingSession={isResettingSession}
      />
    ),
    [
      addToast,
      handleLogin,
      handleLogout,
      handleNewTrip,
      handleStartNewSession,
      hasItineraryContent,
      isGenerating,
      isResettingSession,
      openSheet,
      otherTrips,
      planViewModel.day_cards,
      resumingTripId,
      resumeTrip,
      showHeaderPills,
      tiles,
      tripInputs,
      user,
      userLoading,
    ]
  );

  const mobileInput = useMemo(() => {
    if (isDesktop) return undefined;
    return (
      <MobileChatInput
        onSend={handleMobileSend}
        onStop={handleMobileStopStreaming}
        isProcessing={isGenerating}
        hasDestination={hasDestination}
        hasPlan={hasPlan}
      />
    );
  }, [
    handleMobileSend,
    handleMobileStopStreaming,
    hasDestination,
    hasPlan,
    isDesktop,
    isGenerating,
  ]);

  return {
    plannerContent,
    planViewContent,
    headerContent,
    mobileInput,
  };
}
