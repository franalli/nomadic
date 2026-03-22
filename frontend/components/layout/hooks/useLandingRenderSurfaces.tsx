'use client';

import type { RefObject } from 'react';

import type { ChatPanelHandle } from '@/components/chat/ChatPanel';
import type { PlanResultPayload } from '@/components/layout/hooks/useBranchManager';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import type { AuthUser, UserTripSummary } from '@/state/userStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { DestinationCard, PlanState, PlanViewModel, PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { useHeaderAndMobileContent } from './useHeaderAndMobileContent';
import { usePlannerContent } from './usePlannerContent';
import { usePlanViewContent } from './usePlanViewContent';

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

export function useLandingRenderSurfaces(args: UseLandingRenderSurfacesArgs) {
  const isExpandingItinerary =
    args.generation?.active === true && args.generation.stage === 'itinerary';

  const plannerContent = usePlannerContent({
    chatPanelRef: args.chatPanelRef,
    chatKey: args.chatKey,
    selectedBranchId: args.selectedBranchId,
    handlePlanResultWithReceipt: args.handlePlanResultWithReceipt,
    handleGeneratePlanStartWithSnapshot: args.handleGeneratePlanStartWithSnapshot,
    requestAutoExpandItinerary: args.requestAutoExpandItinerary,
    hasBranchesReady: args.hasBranchesReady,
    readyToGenerate: args.readyToGenerate,
    isGenerating: args.isGenerating,
    planState: args.planState,
    handleUserMessageSubmit: args.handleUserMessageSubmit,
    tripInputs: args.tripInputs,
    hasStartDate: args.hasStartDate,
    hasEndDate: args.hasEndDate,
    hasDestination: args.hasDestination,
    hasDates: args.hasDates,
    bookingTypes: args.bookingTypes,
    flightSettings: args.flightSettings,
    hotelSettings: args.hotelSettings,
    activitySettings: args.activitySettings,
    handleUpdateBookingTypes: args.handleUpdateBookingTypes,
    handleUpdateFlightSettings: args.handleUpdateFlightSettings,
    handleUpdateHotelSettings: args.handleUpdateHotelSettings,
    handleUpdateActivitySettings: args.handleUpdateActivitySettings,
    planViewState: args.planViewState,
    isFraming: args.isFraming,
    openSheet: args.openSheet,
    destinationImageUrl: args.destinationImageUrl,
    handleStartNewSession: args.handleStartNewSession,
    destinationCard: args.destinationCard,
  });

  const planViewContent = usePlanViewContent({
    planViewState: args.planViewState,
    planViewModel: args.planViewModel,
    destinationCard: args.destinationCard,
    tiles: args.tiles,
    generation: args.generation,
    canGeneratePlan: args.canGeneratePlan,
    fallbackTitle: args.fallbackTitle,
    hasDates: args.hasDates,
    isExpandingItinerary,
    handleBuildPlan: args.handleBuildPlan,
    handleExpandToItinerary: args.handleExpandToItinerary,
    handleFinalizePlan: args.handleFinalizePlan,
    isFinalizing: args.isFinalizing,
    preferredTileIds: args.preferredTileIds,
    handleSaveTilePreference: args.handleSaveTilePreference,
    tripInputs: args.tripInputs,
    isCommitting: args.isCommitting,
    openSheet: args.openSheet,
    hasEverHadPlan: args.hasEverHadPlan,
    isRegenerating: args.isRegenerating,
    handleSelectNights: args.handleSelectNights,
    handleOpenGearActivities: args.handleOpenGearActivities,
    handleOpenGearStays: args.handleOpenGearStays,
    handleOpenGearFlights: args.handleOpenGearFlights,
  });

  const { headerContent, mobileInput } = useHeaderAndMobileContent({
    tiles: args.tiles,
    tripInputs: args.tripInputs,
    dayCards: args.planViewModel.day_cards,
    openSheet: args.openSheet,
    isGenerating: args.isGenerating,
    hasItineraryContent: args.hasItineraryContent,
    showHeaderPills: args.showHeaderPills,
    user: args.user,
    otherTrips: args.otherTrips,
    resumingTripId: args.resumingTripId,
    userLoading: args.userLoading,
    handleNewTrip: args.handleNewTrip,
    handleLogin: args.handleLogin,
    handleLogout: args.handleLogout,
    handleStartNewSession: args.handleStartNewSession,
    resumeTrip: args.resumeTrip,
    addToast: args.addToast,
    isResettingSession: args.isResettingSession,
    isDesktop: args.isDesktop,
    handleMobileSend: args.handleMobileSend,
    handleMobileStopStreaming: args.handleMobileStopStreaming,
    hasDestination: args.hasDestination,
    hasPlan: args.hasPlan,
  });

  return {
    plannerContent,
    planViewContent,
    headerContent,
    mobileInput,
  };
}
