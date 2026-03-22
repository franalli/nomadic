'use client';

import { useMemo } from 'react';

import { MobileChatInput } from '@/components/chat/MobileChatInput';
import { LandingHeaderContent } from '@/components/layout/LandingHeaderContent';
import type { AuthUser, UserTripSummary } from '@/state/userStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanViewModel } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

export interface UseHeaderAndMobileContentArgs {
  tiles: Record<string, Tile>;
  tripInputs: DocumentTripInputs;
  dayCards: PlanViewModel['day_cards'];
  openSheet: (name: SheetType) => void;
  isGenerating: boolean;
  hasItineraryContent: boolean;
  showHeaderPills: boolean;
  user: AuthUser | null;
  otherTrips: UserTripSummary[];
  resumingTripId: number | null;
  userLoading: boolean;
  handleNewTrip: () => Promise<void>;
  handleLogin: () => Promise<void>;
  handleLogout: () => Promise<void>;
  handleStartNewSession: () => void | Promise<void>;
  resumeTrip: (tripId: number) => Promise<boolean>;
  addToast: (message: string, type?: ToastType) => void;
  isResettingSession: boolean;
  isDesktop: boolean;
  handleMobileSend: (message: string) => void;
  handleMobileStopStreaming: () => void;
  hasDestination: boolean;
  hasPlan: boolean;
}

export function useHeaderAndMobileContent({
  tiles,
  tripInputs,
  dayCards,
  openSheet,
  isGenerating,
  hasItineraryContent,
  showHeaderPills,
  user,
  otherTrips,
  resumingTripId,
  userLoading,
  handleNewTrip,
  handleLogin,
  handleLogout,
  handleStartNewSession,
  resumeTrip,
  addToast,
  isResettingSession,
  isDesktop,
  handleMobileSend,
  handleMobileStopStreaming,
  hasDestination,
  hasPlan,
}: UseHeaderAndMobileContentArgs) {
  const headerContent = useMemo(
    () => (
      <LandingHeaderContent
        tiles={tiles}
        tripInputs={tripInputs}
        dayCards={dayCards}
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
      dayCards,
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

  return { headerContent, mobileInput };
}
