'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';

import type { ChatPanelHandle } from '@/components/chat/ChatPanel';
import { useLandingControllerStores } from '@/components/layout/hooks/useLandingControllerStores';
import { useLandingPlanState } from '@/components/layout/hooks/useLandingPlanState';
import { useLandingRenderSurfaces } from '@/components/layout/hooks/useLandingRenderSurfaces';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import { useToast } from '@/components/ui/toast';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { startPreferenceAutoRegen } from '@/hooks/usePreferenceAutoRegen';
import { useSheetManager } from '@/hooks/useSheetManager';
import { useViewNavigationLight } from '@/hooks/useViewNavigation';
import { apiFetch } from '@/lib/api';
import type { ToastType } from '@/types/hooks';

export function useNomadicLandingController() {
  const isDesktop = useIsDesktop();
  const {
    mobileNavigateToPlan,
    mobileNavReset,
    mobileSetHasNewContent,
    setActiveView,
    storeReset,
    storeUpdateTripInputs,
    storeCommitTripInputs,
    toggleTilePreference,
    storeTripInputs,
    isCommitting,
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
    preferredTileIds,
    user,
    login,
    logout,
    fetchTrips,
    userLoading,
    resumeTrip,
    resumingTripId,
    trips,
    tripContextId,
  } = useLandingControllerStores();
  const { activeSheet, openSheet, closeSheet } = useSheetManager();
  const { navigateTo, finalizePlan, canViewPlan, activeView } = useViewNavigationLight();
  const chatPanelRef = useRef<ChatPanelHandle | null>(null);
  const otherTrips = useMemo(
    () => (tripContextId ? trips.filter((trip) => trip.trip_id !== tripContextId) : trips),
    [tripContextId, trips]
  );

  useEffect(() => startPreferenceAutoRegen(), []);

  const { toast } = useToast();
  const addToast = useCallback(
    (message: string, type: ToastType = 'info') => {
      const mappedType = type === 'confirmation' ? 'success' : type;
      toast(message, {
        type: mappedType as 'success' | 'info' | 'warning' | 'error',
      });
    },
    [toast]
  );

  useEffect(() => {
    if (user) void fetchTrips();
  }, [fetchTrips, user]);

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

  const planState = useLandingPlanState({
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
    docGeneration: docGeneration as GenerationState | undefined,
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
  });

  const { plannerContent, planViewContent, headerContent, mobileInput } =
    useLandingRenderSurfaces({
      chatPanelRef,
      preferredTileIds,
      isCommitting,
      openSheet,
      user,
      otherTrips,
      resumingTripId,
      userLoading,
      resumeTrip,
      addToast,
      isDesktop,
      handleNewTrip,
      handleLogin,
      handleLogout,
      ...planState,
    });

  return {
    splitLayoutProps: {
      dataDensity: planState.dataDensity,
      plannerContent,
      planViewContent,
      planState: planState.planState,
      onReset: planState.handleStartNewSession,
      isResetting: planState.isResettingSession,
      planTabEnabled: planState.planTabEnabled,
      mobileStatusBar: undefined,
      mobileInput,
      headerContent,
    },
    landingSheetsProps: {
      tripInputs: planState.tripInputs,
      hasDestination: planState.hasDestination,
      hasOrigin: planState.hasOrigin,
      hasDates: planState.hasDates,
      planViewState: planState.planViewState ?? undefined,
      activeSheet,
      gearActivitiesSheetOpen: planState.gearActivitiesSheetOpen,
      gearStaysSheetOpen: planState.gearStaysSheetOpen,
      gearFlightsSheetOpen: planState.gearFlightsSheetOpen,
      setGearActivitiesSheetOpen: planState.setGearActivitiesSheetOpen,
      setGearStaysSheetOpen: planState.setGearStaysSheetOpen,
      setGearFlightsSheetOpen: planState.setGearFlightsSheetOpen,
      closeSheet,
      openSheet,
      addToast,
      storeUpdateTripInputs,
      storeCommitTripInputs,
      handleUpdateActivitySettings: planState.handleUpdateActivitySettings,
      onSendMessage: planState.handleSendMessage,
    },
    floatingBuildButtonProps: {
      visible: false,
      onClick: planState.handleBuildPlan,
      isGenerating: planState.isGenerating,
      hasEverHadPlan: planState.hasEverHadPlan,
    },
  };
}
