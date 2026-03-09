'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useStoreWithEqualityFn } from 'zustand/traditional';

import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { MobileChatInput } from '@/components/chat/MobileChatInput';
import { FloatingBuildButton } from '@/components/layout/FloatingBuildButton';
import {
  useBranchManager,
} from '@/components/layout/hooks/useBranchManager';
import { useItineraryGeneration } from '@/components/layout/hooks/useItineraryGeneration';
import { useLandingDerived } from '@/components/layout/hooks/useLandingDerived';
import { useLandingEffects } from '@/components/layout/hooks/useLandingEffects';
import { useLandingHandlers } from '@/components/layout/hooks/useLandingHandlers';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import { LandingHeaderContent } from '@/components/layout/LandingHeaderContent';
import { LandingSheets } from '@/components/layout/LandingSheets';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { computeDataDensity, type DataDensity, StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { startPreferenceAutoRegen } from '@/hooks/usePreferenceAutoRegen';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useViewNavigationLight } from '@/hooks/useViewNavigation';
import { apiFetch } from '@/lib/api';
import { formatDateForDisplay } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import { useUserStore } from '@/state/userStore';
import type { ToastType } from '@/types/hooks';

export function NomadicLanding() {
  // ─── Viewport & mobile nav ───────────────────────────────────────────────
  const isDesktop = useIsDesktop();
  const { mobileNavigateToPlan, mobileNavReset, mobileSetHasNewContent } =
    useMobileNavStore(
      useShallow((s) => ({
        mobileNavigateToPlan: s.navigateToPlan,
        mobileNavReset: s.reset,
        mobileSetHasNewContent: s.setHasNewPlanContent,
      }))
    );

  // ─── Document store selectors ────────────────────────────────────────────

  // Actions (stable references)
  const {
    setActiveView,
    storeReset,
    storeUpdateTripInputs,
    storeCommitTripInputs,
    toggleTilePreference,
  } = useDocumentStore(
    useShallow((s) => ({
      setActiveView: s.setActiveView,
      storeReset: s.reset,
      storeUpdateTripInputs: s.updateTripInputs,
      storeCommitTripInputs: s.commitTripInputs,
      toggleTilePreference: s.toggleTilePreference,
    }))
  );

  // Reactive document data
  const { storeTripInputs, isCommitting } = useDocumentStore(
    useShallow((s) => ({
      storeTripInputs: s.document?.trip_inputs,
      isCommitting: s.isCommitting,
    }))
  );

  // Layout state — rarely changes
  const { docPlanViewState, docPlanState, docDestinationCard } = useDocumentStore(
    useShallow((s) => ({
      docPlanViewState: s.document?.plan_view_state,
      docPlanState: s.document?.plan_state,
      docDestinationCard: s.document?.destination_card,
    }))
  );

  // Content state — changes on plan updates
  const { docStrategySections, docTiles, docDayCards, docExecutedTopics, docPendingTopics } = useDocumentStore(
    useShallow((s) => ({
      docStrategySections: s.document?.strategy_sections,
      docTiles: s.document?.tiles,
      docDayCards: s.document?.day_cards,
      docExecutedTopics: s.document?.executed_strategy_topics,
      docPendingTopics: s.document?.pending_strategy_topics,
    }))
  );

  // Status state — changes frequently
  const { docGeneration, docNeedsRefresh, docCanExpand, docOpenDecisions, docItineraryOverview, docItineraryAssumptions } = useDocumentStore(
    useShallow((s) => ({
      docGeneration: s.generation,
      docNeedsRefresh: s.document?.needs_refresh,
      docCanExpand: s.document?.can_expand_to_itinerary,
      docOpenDecisions: s.document?.open_decisions,
      docItineraryOverview: s.document?.itinerary_overview,
      docItineraryAssumptions: s.document?.itinerary_assumptions,
    }))
  );

  // preferredTileIds is a Set — useShallow uses Object.is() which always
  // returns false for new Set references even with identical contents.
  // Custom equality compares Set contents instead.
  const preferredTileIds = useStoreWithEqualityFn(
    useDocumentStore,
    (s) => s.preferredTileIds,
    (a, b) => a.size === b.size && [...a].every((id) => b.has(id)),
  );

  const { user, trips, login, logout, fetchTrips, userLoading, resumeTrip, resumingTripId } = useUserStore(
    useShallow((s) => ({
      user: s.user,
      trips: s.trips,
      login: s.login,
      logout: s.logout,
      fetchTrips: s.fetchTrips,
      userLoading: s.loading,
      resumeTrip: s.resumeTrip,
      resumingTripId: s.resumingTripId,
    }))
  );

  // ─── Shared hooks ────────────────────────────────────────────────────────

  const { activeSheet, openSheet, closeSheet } = useSheetManager();
  const { navigateTo, finalizePlan, canViewPlan, activeView } = useViewNavigationLight();
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  useEffect(() => {
    return startPreferenceAutoRegen();
  }, []);

  // ─── Local state ─────────────────────────────────────────────────────────

  const [userRequestedGeneration, setUserRequestedGeneration] = useState(false);

  // State managed by effects but owned here (avoids circular deps with derived)
  const [hasEverHadPlan, setHasEverHadPlan] = useState(false);
  const [localPendingTopics, setLocalPendingTopics] = useState<string[]>([]);
  const [destinationImageUrl, setDestinationImageUrl] = useState<string | null>(null);

  // Toast system
  const { toast } = useToast();
  const addToast = useCallback(
    (message: string, type: ToastType = 'info') => {
      const mappedType = type === 'confirmation' ? 'success' : type;
      toast(message, { type: mappedType as 'success' | 'info' | 'warning' | 'error' });
    },
    [toast]
  );
  useEffect(() => {
    if (user) void fetchTrips();
  }, [fetchTrips, user]);

  const tripContextId = useDocumentStore((s) => s.document?.trip_context_id);
  const otherTrips = useMemo(
    () => (tripContextId ? trips.filter((t) => t.trip_id !== tripContextId) : trips),
    [trips, tripContextId]
  );

  const handleNewTrip = useCallback(async () => {
    try {
      await apiFetch('/api/session/new', { method: 'POST' });
      window.location.reload();
    } catch {
      addToast('Could not start new trip', 'error');
    }
  }, [addToast]);

  const handleLogin = useCallback(async () => {
    try {
      await login();
    } catch {
      addToast('Could not start sign in', 'error');
    }
  }, [addToast, login]);

  const handleLogout = useCallback(async () => {
    await logout();
    addToast('Signed out', 'info');
  }, [addToast, logout]);

  // Local UI generation state
  const [uiGeneration, setUiGeneration] = useState<GenerationState | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);

  // Local booking settings
  const {
    bookingTypes,
    flightSettings,
    hotelSettings,
    activitySettings,
    handleUpdateBookingTypes,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateActivitySettings,
  } = useLocalBookingSettings(storeTripInputs, addToast);

  // Branch manager
  const tripInputsEditorRefForBranch = useRef<ReturnType<typeof useTripInputsEditor> | null>(null);
  const branchManager = useBranchManager({
    chatPanelContainerRef,
    onToast: addToast,
    onChatKeyIncrement: useCallback(() => setChatKey((prev) => prev + 1), []),
    resetDraft: () => tripInputsEditorRefForBranch.current?.resetDraft(),
  });

  const {
    selectedBranchId,
    isGenerating,
    isRegenerating,
    readyToGenerate,
    hasBranchesReady,
    handleStartNewSession: branchManagerStartNewSession,
    handlePlanResult,
    handleGeneratePlanStart,
  } = branchManager;

  // ─── Derived computations ────────────────────────────────────────────────

  const {
    tripInputs,
    planState,
    destinationCard,
    planViewState,
    isFraming,
    planViewModel,
    generation,
    tiles,
    planTabEnabled,
    canGeneratePlan,
    hasDates,
    hasPlan,
    fallbackTitle,
    hasOrigin,
    hasDestination,
    hasStartDate,
    hasEndDate,
    hasStrategyContent,
    hasTilesReady,
    hasDayCardsReady,
    docTileCount,
  } = useLandingDerived({
    storeTripInputs,
    docPlanState,
    docDestinationCard,
    docPlanViewState,
    docStrategySections,
    docTiles,
    docExecutedTopics,
    docPendingTopics,
    docDayCards,
    docGeneration: docGeneration as GenerationState | undefined,
    docOpenDecisions,
    docItineraryOverview,
    docItineraryAssumptions,
    docNeedsRefresh,
    docCanExpand,
    destinationImageUrl,
    isGenerating,
    hasEverHadPlan,
    userRequestedGeneration,
    uiGeneration,
    localPendingTopics,
    hasBranchesReady,
  });

  // Compute data density for adaptive layout
  const dataDensity: DataDensity = hasDestination
    ? computeDataDensity(
        planViewState ?? 'P0_MINIMAL',
        planViewModel.strategy_sections,
        tiles,
        hasDates
      )
    : 'empty';

  // Header pills visibility — show when there's a destination and real plan data
  const showHeaderPills = hasDestination && dataDensity !== 'empty';

  // Trip inputs editor
  const tripInputsEditor = useTripInputsEditor({
    tripInputs,
    storeTripInputs,
    onToast: addToast,
  });

  // ─── Side effects ────────────────────────────────────────────────────────

  const { tripInputsEditorRef, finalizeTimerRef } = useLandingEffects({
    tripInputs,
    planViewState,
    isFraming,
    docExecutedTopics,
    hasBranchesReady,
    hasStrategyContent,
    hasTilesReady,
    hasDayCardsReady,
    userRequestedGeneration,
    docTileCount,
    isDesktop,
    hasDates,
    canViewPlan,
    activeView,
    setActiveView,
    toast,
    mobileNavigateToPlan,
    mobileSetHasNewContent,
    tripInputsEditor,
    hasEverHadPlan,
    setHasEverHadPlan,
    setLocalPendingTopics,
    setDestinationImageUrl,
    isHydrating: branchManager.isHydratingSnapshot,
  });

  // Sync refs for branchManager resetDraft callback
  tripInputsEditorRef.current = tripInputsEditor;
  tripInputsEditorRefForBranch.current = tripInputsEditor;

  // ─── Itinerary generation ────────────────────────────────────────────────

  const {
    proceedWithItineraryGeneration,
    requestAutoExpandItinerary,
    handleExpandToItinerary,
    handleSelectNights,
    hasItineraryContent,
  } = useItineraryGeneration({
    uiGeneration,
    setUiGeneration,
    addToast,
    planViewState: planViewState ?? undefined,
    docExecutedTopics,
    hasDates,
    docDayCards,
    isRegenerating,
    tripInputsStartDate: tripInputs.start_date,
  });

  // ─── Event handlers (extracted to useLandingHandlers) ────────────────────

  const {
    handleStartNewSession,
    handleSaveTilePreference,
    handleOpenGearActivities,
    handleOpenGearStays,
    handleOpenGearFlights,
    handleGeneratePlanStartWithSnapshot,
    handlePlanResultWithReceipt,
    handleUserMessageSubmit,
    handleBuildPlan,
    handleFinalizePlan,
    handleMobileSend,
    handleMobileStopStreaming,
    handleSendMessage,
    isResettingSession,
    isFinalizing,
    gearActivitiesSheetOpen,
    gearStaysSheetOpen,
    gearFlightsSheetOpen,
    setGearActivitiesSheetOpen,
    setGearStaysSheetOpen,
    setGearFlightsSheetOpen,
  } = useLandingHandlers({
    storeReset,
    toggleTilePreference,
    storeTripInputs,
    closeSheet,
    mobileNavReset,
    mobileNavigateToPlan,
    navigateTo,
    finalizePlan,
    branchManagerStartNewSession,
    handlePlanResult,
    handleGeneratePlanStart,
    hasEverHadPlan,
    setHasEverHadPlan,
    setLocalPendingTopics,
    setDestinationImageUrl,
    finalizeTimerRef,
    chatPanelRef,
    setUiGeneration,
    setUserRequestedGeneration,
    setChatKey,
  });

  // ─── JSX ─────────────────────────────────────────────────────────────────

  const plannerContent = useMemo(() => (
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
  ), [
    chatPanelRef, chatKey, selectedBranchId, handlePlanResultWithReceipt,
    handleGeneratePlanStartWithSnapshot, requestAutoExpandItinerary,
    hasBranchesReady, readyToGenerate, isGenerating, planState,
    handleUserMessageSubmit, tripInputs, hasStartDate, hasEndDate,
    hasDestination, hasDates, bookingTypes, flightSettings, hotelSettings,
    activitySettings, handleUpdateBookingTypes, handleUpdateFlightSettings,
    handleUpdateHotelSettings, handleUpdateActivitySettings, planViewState,
    isFraming, openSheet, destinationCard, destinationImageUrl, handleStartNewSession,
  ]);

  const isExpandingItinerary = generation?.stage === 'itinerary';

  const planViewContent = useMemo(() => (
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
  ), [
    planViewState, planViewModel, destinationCard, tiles, generation,
    canGeneratePlan, fallbackTitle, hasDates, isExpandingItinerary,
    handleBuildPlan, handleExpandToItinerary, handleFinalizePlan,
    isFinalizing, preferredTileIds, handleSaveTilePreference, tripInputs,
    isCommitting, openSheet, hasEverHadPlan, isRegenerating, handleSelectNights,
    handleOpenGearActivities, handleOpenGearStays, handleOpenGearFlights,
  ]);

  return (
    <>
      <div className="appTopo text-foreground">
        <SplitLayoutView
          dataDensity={dataDensity}
          plannerContent={plannerContent}
          planViewContent={planViewContent}
          planState={planState}
          onReset={handleStartNewSession}
          isResetting={isResettingSession}
          planTabEnabled={planTabEnabled}
          mobileStatusBar={undefined}
          mobileInput={
            !isDesktop ? (
              <MobileChatInput
                onSend={handleMobileSend}
                onStop={handleMobileStopStreaming}
                isProcessing={isGenerating}
                hasDestination={hasDestination}
                hasPlan={hasPlan}
              />
            ) : undefined
          }
          headerContent={
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
          }
        />

        <FloatingBuildButton
          visible={false}
          onClick={handleBuildPlan}
          isGenerating={isGenerating}
          hasEverHadPlan={hasEverHadPlan}
        />
      </div>

      <LandingSheets
        tripInputs={tripInputs}
        hasDestination={hasDestination}
        hasOrigin={hasOrigin}
        hasDates={hasDates}
        hasItinerary={hasItineraryContent}
        planViewState={planViewState ?? undefined}
        activeSheet={activeSheet}
        gearActivitiesSheetOpen={gearActivitiesSheetOpen}
        gearStaysSheetOpen={gearStaysSheetOpen}
        gearFlightsSheetOpen={gearFlightsSheetOpen}
        setGearActivitiesSheetOpen={setGearActivitiesSheetOpen}
        setGearStaysSheetOpen={setGearStaysSheetOpen}
        setGearFlightsSheetOpen={setGearFlightsSheetOpen}
        closeSheet={closeSheet}
        openSheet={openSheet}
        addToast={addToast}
        storeUpdateTripInputs={storeUpdateTripInputs}
        storeCommitTripInputs={storeCommitTripInputs}
        proceedWithItineraryGeneration={proceedWithItineraryGeneration}
        handleUpdateActivitySettings={handleUpdateActivitySettings}
        onSendMessage={handleSendMessage}
      />
    </>
  );
}

export default function NomadicLandingWithProvider() {
  return (
    <ErrorBoundary label="App">
      <NomadicLanding />
    </ErrorBoundary>
  );
}
