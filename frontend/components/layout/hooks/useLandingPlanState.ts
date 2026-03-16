'use client';

import type { RefObject } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';

import type { ChatPanelHandle } from '@/components/chat/ChatPanel';
import { useBranchManager } from '@/components/layout/hooks/useBranchManager';
import { useItineraryGeneration } from '@/components/layout/hooks/useItineraryGeneration';
import { useLandingDerived } from '@/components/layout/hooks/useLandingDerived';
import { useLandingEffects } from '@/components/layout/hooks/useLandingEffects';
import { useLandingHandlers } from '@/components/layout/hooks/useLandingHandlers';
import { useLocalBookingSettings } from '@/components/layout/hooks/useLocalBookingSettings';
import { useTripInputsEditor } from '@/components/layout/hooks/useTripInputsEditor';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { computeDataDensity, type DataDensity } from '@/components/plan/StrategyStageRenderer';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type {
  DayCard,
  DestinationCard,
  ItineraryAssumptions,
  ItineraryOverview,
  OpenDecision,
  PlanState,
  PlanViewState,
  StrategySection,
} from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

interface UseLandingPlanStateArgs {
  isDesktop: boolean;
  activeView: 'setup' | 'plan' | 'book';
  canViewPlan: boolean;
  mobileNavigateToPlan: () => void;
  mobileNavReset: () => void;
  mobileSetHasNewContent: (hasNewContent: boolean) => void;
  setActiveView: (view: 'planning' | 'booking') => void;
  storeReset: () => void;
  toggleTilePreference: (tileId: string) => void;
  storeTripInputs: DocumentTripInputs | undefined;
  docPlanViewState: PlanViewState | undefined;
  docPlanState: PlanState | undefined;
  docDestinationCard: DestinationCard | null | undefined;
  docStrategySections: StrategySection[] | undefined;
  docTiles: Record<string, Tile> | undefined;
  docDayCards: DayCard[] | undefined;
  docExecutedTopics: string[] | undefined;
  docPendingTopics: string[] | undefined;
  docGeneration: GenerationState | undefined;
  docNeedsRefresh: boolean | undefined;
  docCanExpand: boolean | undefined;
  docOpenDecisions: OpenDecision[] | undefined;
  docItineraryOverview: ItineraryOverview | null | undefined;
  docItineraryAssumptions: ItineraryAssumptions | null | undefined;
  closeSheet: () => void;
  navigateTo: (view: 'setup' | 'plan' | 'book') => boolean;
  finalizePlan: () => void;
  toast: (message: string, options?: { type?: 'success' | 'info' | 'warning' | 'error' }) => void;
  addToast: (message: string, type?: ToastType) => void;
  chatPanelRef: RefObject<ChatPanelHandle | null>;
}

export function computeLayoutDataDensity({
  hasDestination,
  planViewState,
  strategySections,
  tiles,
  hasDates,
  generation,
}: {
  hasDestination: boolean;
  planViewState: PlanViewState | null;
  strategySections: StrategySection[] | undefined;
  tiles: Record<string, Tile>;
  hasDates: boolean;
  generation: GenerationState | null;
}): DataDensity {
  if (generation?.active === true) {
    return 'ghost';
  }

  if (!hasDestination) {
    return 'empty';
  }

  return computeDataDensity(
    planViewState ?? 'P0_MINIMAL',
    strategySections,
    tiles,
    hasDates
  );
}

export function useLandingPlanState({
  isDesktop,
  activeView,
  canViewPlan,
  mobileNavigateToPlan,
  mobileNavReset,
  mobileSetHasNewContent,
  setActiveView,
  storeReset,
  toggleTilePreference,
  storeTripInputs,
  docPlanViewState,
  docPlanState,
  docDestinationCard,
  docStrategySections,
  docTiles,
  docDayCards,
  docExecutedTopics,
  docPendingTopics,
  docGeneration,
  docNeedsRefresh,
  docCanExpand,
  docOpenDecisions,
  docItineraryOverview,
  docItineraryAssumptions,
  closeSheet,
  navigateTo,
  finalizePlan,
  toast,
  addToast,
  chatPanelRef,
}: UseLandingPlanStateArgs) {
  const [userRequestedGeneration, setUserRequestedGeneration] = useState(false);
  const [hasEverHadPlan, setHasEverHadPlan] = useState(false);
  const [localPendingTopics, setLocalPendingTopics] = useState<string[]>([]);
  const [destinationImageUrl, setDestinationImageUrl] = useState<string | null>(null);
  const [uiGeneration, setUiGeneration] = useState<GenerationState | null>(null);
  const [chatKey, setChatKey] = useState(0);
  const chatPanelContainerRef = useRef<HTMLDivElement | null>(null);

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

  const tripInputsEditorRefForBranch =
    useRef<ReturnType<typeof useTripInputsEditor> | null>(null);
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
    docGeneration,
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

  const dataDensity = computeLayoutDataDensity({
    hasDestination,
    planViewState,
    strategySections: planViewModel.strategy_sections,
    tiles,
    hasDates,
    generation,
  });
  const showHeaderPills = hasDestination && dataDensity !== 'empty';

  const tripInputsEditor = useTripInputsEditor({
    tripInputs,
    storeTripInputs,
    onToast: addToast,
  });

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

  useEffect(() => {
    tripInputsEditorRef.current = tripInputsEditor;
    tripInputsEditorRefForBranch.current = tripInputsEditor;
  }, [tripInputsEditor, tripInputsEditorRef]);

  const {
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

  return {
    chatKey,
    selectedBranchId,
    readyToGenerate,
    hasBranchesReady,
    isGenerating,
    isRegenerating,
    planState,
    tripInputs,
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
    bookingTypes,
    flightSettings,
    hotelSettings,
    activitySettings,
    handleUpdateBookingTypes,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateActivitySettings,
    requestAutoExpandItinerary,
    handleExpandToItinerary,
    handleSelectNights,
    hasItineraryContent,
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
    hasEverHadPlan,
    destinationImageUrl,
    dataDensity,
    showHeaderPills,
  };
}
