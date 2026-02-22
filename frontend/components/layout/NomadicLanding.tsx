'use client';

import { Compass, Loader2, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { StartupSequence } from '@/components/animations/StartupSequence';
import { ChatPanel, type ChatPanelHandle } from '@/components/chat/ChatPanel';
import { MobileChatInput } from '@/components/chat/MobileChatInput';
import { TripStatusBar } from '@/components/chat/TripStatusBar';
import { FloatingBuildButton } from '@/components/layout/FloatingBuildButton';
import {
  type PlanResultPayload,
  useBranchManager,
} from '@/components/layout/hooks/useBranchManager';
import { useItineraryGeneration } from '@/components/layout/hooks/useItineraryGeneration';
import { useLandingDerived } from '@/components/layout/hooks/useLandingDerived';
import { useLandingEffects } from '@/components/layout/hooks/useLandingEffects';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import {
  type ChangeReceiptData,
  detectChangedFieldNames,
  detectTopicsFromMessage,
  RESET_BUTTON_COOLDOWN_MS,
} from '@/components/layout/LandingHelpers';
import { LandingSheets } from '@/components/layout/LandingSheets';
import { SplitLayoutView } from '@/components/layout/SplitLayoutView';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { computeDataDensity, type DataDensity, StrategyStageRenderer } from '@/components/plan/StrategyStageRenderer';
import { Button } from '@/components/ui/button';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { startPreferenceAutoRegen } from '@/hooks/usePreferenceAutoRegen';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useViewNavigationLight } from '@/hooks/useViewNavigation';
import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import { formatDateForDisplay } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { Tile } from '@/types/tile';

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

  // Trip inputs + commit state
  const { storeTripInputs, isCommitting } = useDocumentStore(
    useShallow((s) => ({
      storeTripInputs: s.document?.trip_inputs,
      isCommitting: s.isCommitting,
    }))
  );

  // Plan document data (for rendering)
  const {
    docPlanState,
    docDestinationCard,
    docPlanViewState,
    docStrategySections,
    docTiles,
    docExecutedTopics,
    docPendingTopics,
    docDayCards,
    docGeneration,
    docOpenDecisions,
    docItineraryOverview,
    docItineraryAssumptions,
    docNeedsRefresh,
    docCanExpand,
    preferredTileIds,
  } = useDocumentStore(
    useShallow((s) => ({
      docPlanState: s.document?.plan_state,
      docDestinationCard: s.document?.destination_card,
      docPlanViewState: s.document?.plan_view_state,
      docStrategySections: s.document?.strategy_sections,
      docTiles: s.document?.tiles,
      docExecutedTopics: s.document?.executed_strategy_topics,
      docPendingTopics: s.document?.pending_strategy_topics,
      docDayCards: s.document?.day_cards,
      docGeneration: s.generation,
      docOpenDecisions: s.document?.open_decisions,
      docItineraryOverview: s.document?.itinerary_overview,
      docItineraryAssumptions: s.document?.itinerary_assumptions,
      docNeedsRefresh: s.document?.needs_refresh,
      docCanExpand: s.document?.can_expand_to_itinerary,
      preferredTileIds: s.preferredTileIds,
    }))
  );

  // ─── Shared hooks ────────────────────────────────────────────────────────

  const { activeSheet, openSheet, closeSheet } = useSheetManager();
  const { navigateTo, finalizePlan, canViewPlan, activeView } = useViewNavigationLight();
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  useEffect(() => startPreferenceAutoRegen(), []);

  // ─── Local state ─────────────────────────────────────────────────────────

  const receiptDataRef = useRef<ChangeReceiptData | null>(null);
  const previousTripInputsRef = useRef<DocumentTripInputs | null>(null);
  const [userRequestedGeneration, setUserRequestedGeneration] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [gearActivitiesSheetOpen, setGearActivitiesSheetOpen] = useState(false);
  const [gearStaysSheetOpen, setGearStaysSheetOpen] = useState(false);
  const [gearFlightsSheetOpen, setGearFlightsSheetOpen] = useState(false);

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

  // Local UI generation state
  const [uiGeneration, setUiGeneration] = useState<GenerationState | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);
  const [isResettingSession, setIsResettingSession] = useState(false);
  const resetInFlightRef = useRef(false);
  const resetCooldownUntilRef = useRef(0);

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
  const dataDensity: DataDensity = computeDataDensity(
    planViewState ?? 'S0_BOOTSTRAP',
    planViewModel.strategy_sections,
    docTiles ?? {}
  );

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
  });

  // Sync refs for branchManager resetDraft callback
  tripInputsEditorRef.current = tripInputsEditor;
  tripInputsEditorRefForBranch.current = tripInputsEditor;

  // ─── Itinerary generation ────────────────────────────────────────────────

  const {
    proceedWithItineraryGeneration,
    handleExpandToItinerary,
    handleSelectNights,
    hasItineraryContent,
  } = useItineraryGeneration({
    uiGeneration,
    setUiGeneration,
    addToast,
    planViewState,
    docExecutedTopics,
    hasDates,
    docDayCards,
    isRegenerating,
    tripInputsStartDate: tripInputs.start_date,
  });

  // ─── Event handlers ──────────────────────────────────────────────────────

  const handleStartNewSession = useCallback(async () => {
    const now = Date.now();
    if (resetInFlightRef.current || now < resetCooldownUntilRef.current) return;
    resetInFlightRef.current = true;
    setIsResettingSession(true);
    debugLog('[handleStartNewSession] Reset triggered');
    try {
      storeReset();
      useChatStore.getState().resetChat();
      setUiGeneration(null);
      receiptDataRef.current = null;
      previousTripInputsRef.current = null;
      setHasEverHadPlan(false);
      setUserRequestedGeneration(false);
      setLocalPendingTopics([]);
      setDestinationImageUrl(null);
      setIsFinalizing(false);
      setGearActivitiesSheetOpen(false);
      setGearStaysSheetOpen(false);
      setGearFlightsSheetOpen(false);
      closeSheet();
      if (!isDesktop) mobileNavReset();
      await branchManagerStartNewSession();
      debugLog('[handleStartNewSession] Reset complete');
    } catch (error) {
      console.error('[handleStartNewSession] Reset failed:', error);
    } finally {
      resetInFlightRef.current = false;
      resetCooldownUntilRef.current = Date.now() + RESET_BUTTON_COOLDOWN_MS;
      setIsResettingSession(false);
    }
  }, [branchManagerStartNewSession, closeSheet, storeReset, isDesktop, mobileNavReset]);

  const handleSaveTilePreference = useCallback(
    (tile: Tile) => { toggleTilePreference(tile.id); },
    [toggleTilePreference]
  );
  const handleOpenGearActivities = useCallback(() => setGearActivitiesSheetOpen(true), []);
  const handleOpenGearStays = useCallback(() => setGearStaysSheetOpen(true), []);
  const handleOpenGearFlights = useCallback(() => setGearFlightsSheetOpen(true), []);

  const handleGeneratePlanStartWithSnapshot = useCallback(() => {
    previousTripInputsRef.current = storeTripInputs ? { ...storeTripInputs } : null;
    setUserRequestedGeneration(true);
    handleGeneratePlanStart();
    navigateTo('plan');
    if (!isDesktop) mobileNavigateToPlan();
  }, [storeTripInputs, handleGeneratePlanStart, navigateTo, isDesktop, mobileNavigateToPlan]);

  const handlePlanResultWithReceipt = useCallback(
    (result: PlanResultPayload) => {
      handlePlanResult(result);
      const newInputs = result.response?.document?.trip_inputs ?? null;
      const changedFields = detectChangedFieldNames(previousTripInputsRef.current, newInputs);
      if (changedFields.length > 0) {
        receiptDataRef.current = {
          type: changedFields.length === 1 ? 'partial' : 'updated',
          fields: changedFields,
          canUndo: true,
        };
      }
    },
    [handlePlanResult]
  );

  const handleUserMessageSubmit = useCallback(
    (message: string) => {
      if (!hasEverHadPlan) return;
      const detectedTopics = detectTopicsFromMessage(message);
      const existingTopics = new Set(
        useDocumentStore.getState().document?.executed_strategy_topics ?? []
      );
      const newTopics = detectedTopics.filter((t) => !existingTopics.has(t));
      if (newTopics.length > 0) {
        setLocalPendingTopics((prev) =>
          Array.from(new Map([...prev, ...newTopics].map((t) => [t, true])).keys())
        );
      }
    },
    [hasEverHadPlan]
  );

  const handleBuildPlan = useCallback(() => {
    chatPanelRef.current?.sendMessage?.(GENERATE_PLAN_TRIGGER);
  }, []);

  const handleFinalizePlan = useCallback(() => {
    setIsFinalizing(true);
    finalizeTimerRef.current = setTimeout(() => {
      finalizeTimerRef.current = null;
      finalizePlan();
      navigateTo('book');
      setIsFinalizing(false);
    }, 1500);
  }, [finalizePlan, navigateTo, finalizeTimerRef]);

  const handleMobileSend = useCallback((message: string) => {
    if (!chatPanelRef.current?.sendMessage) {
      debugLog('[MobileChatInput] ChatPanel ref not ready');
      return;
    }
    chatPanelRef.current.sendMessage(message);
  }, []);

  const handleMobileStopStreaming = useCallback(() => {
    chatPanelRef.current?.stopStreaming?.();
  }, []);

  const handleSendMessage = useCallback((msg: string) => {
    chatPanelRef.current?.sendMessage?.(msg);
  }, []);

  // ─── JSX ─────────────────────────────────────────────────────────────────

  const plannerContent = (
    <ErrorBoundary label="Chat">
      <ChatPanel
        ref={chatPanelRef}
        key={chatKey}
        selectedBranchId={selectedBranchId}
        onPlanResult={handlePlanResultWithReceipt}
        onGeneratePlanStart={handleGeneratePlanStartWithSnapshot}
        onAutoExpandItinerary={proceedWithItineraryGeneration}
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
        planViewState={planViewState}
        onOpenSheet={openSheet}
        destinationImageUrl={destinationCard?.image_url ?? destinationImageUrl}
      />
    </ErrorBoundary>
  );

  const isExpandingItinerary = generation?.stage === 'itinerary';

  const planViewContent = (
    <ErrorBoundary label="Plan View">
      <StrategyStageRenderer
        state={planViewState}
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
  );

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
          mobileStatusBar={
            !isDesktop &&
            (hasDestination ||
              Boolean(tripInputs.origin) ||
              Boolean(tripInputs.start_date)) ? (
              <TripStatusBar
                tripInputs={tripInputs}
                specialists={docExecutedTopics ?? []}
                onOpenSheet={openSheet}
              />
            ) : undefined
          }
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
            <div className="flex w-full items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <Compass className="text-primary h-5 w-5" />
                  <span className="text-foreground text-lg font-semibold">Nomadic</span>
                </div>
                <span className="text-foreground hidden text-sm sm:inline">
                  <span className="text-muted-foreground/30 mx-2">|</span>
                  Change your mind. Keep the plan.
                </span>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleStartNewSession}
                disabled={isResettingSession}
                className={`${DS.textSize.micro} font-bold uppercase tracking-widest text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-500 dark:hover:bg-white/5 dark:hover:text-white disabled:opacity-60 disabled:pointer-events-none`}
              >
                {isResettingSession ? (
                  <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="mr-1.5 h-3 w-3" />
                )}
                {isResettingSession ? 'Resetting' : 'Reset'}
              </Button>
            </div>
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
        planViewState={planViewState}
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

// Inner component with startup animation
function AppWithStartup() {
  const [hasBooted, setHasBooted] = useState(false);

  return (
    <>
      {!hasBooted && <StartupSequence onComplete={() => setHasBooted(true)} />}
      <div
        className={
          hasBooted ? 'opacity-100 transition-opacity duration-300' : 'opacity-0'
        }
      >
        <ErrorBoundary label="App">
          <NomadicLanding />
        </ErrorBoundary>
      </div>
    </>
  );
}

export default function NomadicLandingWithProvider() {
  return <AppWithStartup />;
}
