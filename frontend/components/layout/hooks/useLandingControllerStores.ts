'use client';

import { useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useStoreWithEqualityFn } from 'zustand/traditional';

import { useDocumentStore } from '@/state/documentStore';
import { useMobileNavStore } from '@/state/mobileNavStore';
import { useUserStore } from '@/state/userStore';

export function useLandingControllerStores() {
  const mobileNavStore = useMobileNavStore(
    useShallow((s) => ({
      mobileNavigateToPlan: s.navigateToPlan,
      mobileNavReset: s.reset,
      mobileSetHasNewContent: s.setHasNewPlanContent,
    }))
  );

  const documentStore = useDocumentStore(
    useShallow((s) => ({
      setActiveView: s.setActiveView,
      storeReset: s.reset,
      storeUpdateTripInputs: s.updateTripInputs,
      storeCommitTripInputs: s.commitTripInputs,
      toggleTilePreference: s.toggleTilePreference,
      storeTripInputs: s.document?.trip_inputs,
      isCommitting: s.isCommitting,
      docPlanViewState: s.document?.plan_view_state,
      docPlanState: s.document?.plan_state,
      docDestinationCard: s.document?.destination_card,
      docStrategySections: s.document?.strategy_sections,
      docTiles: s.document?.tiles,
      docDayCards: s.document?.day_cards,
      docExecutedTopics: s.document?.executed_strategy_topics,
      docPendingTopics: s.document?.pending_strategy_topics,
      docGeneration: s.generation,
      docNeedsRefresh: s.document?.needs_refresh,
      docCanExpand: s.document?.can_expand_to_itinerary,
      docOpenDecisions: s.document?.open_decisions,
      docItineraryOverview: s.document?.itinerary_overview,
      docItineraryAssumptions: s.document?.itinerary_assumptions,
      tripContextId: s.document?.trip_context_id,
    }))
  );

  const preferredTileIds = useStoreWithEqualityFn(
    useDocumentStore,
    (s) => s.preferredTileIds,
    (a, b) => a.size === b.size && [...a].every((id) => b.has(id))
  );

  const userStore = useUserStore(
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

  const otherTrips = useMemo(
    () =>
      documentStore.tripContextId
        ? userStore.trips.filter((trip) => trip.trip_id !== documentStore.tripContextId)
        : userStore.trips,
    [documentStore.tripContextId, userStore.trips]
  );

  return {
    ...mobileNavStore,
    ...documentStore,
    preferredTileIds,
    ...userStore,
    otherTrips,
  };
}
