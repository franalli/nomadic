'use client';

import { Compass, Loader2, LogIn, RotateCcw } from 'lucide-react';
import { memo, useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { Button } from '@/components/ui/button';
import type { ToastType } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { AuthUser, UserTripSummary } from '@/state/userStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { LandingHeaderUserMenu } from './LandingHeaderUserMenu';

interface LandingHeaderContentProps {
  tiles: Record<string, Tile>;
  tripInputs: DocumentTripInputs;
  dayCards: DayCard[] | undefined;
  openSheet: (sheet: SheetType) => void;
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
  handleStartNewSession: () => void;
  resumeTrip: (tripId: number) => Promise<boolean>;
  addToast: (message: string, type?: ToastType) => void;
  isResettingSession: boolean;
}

export const LandingHeaderContent = memo(function LandingHeaderContent({
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
}: LandingHeaderContentProps) {
  const {
    staysExpanded: headerStaysActive,
    flightsExpanded: headerFlightsActive,
    intelExpanded: headerIntelActive,
    travelAdviceCount: headerAdviceCount,
    showTravelAdvice: headerShowAdvice,
    isTravelAdvicePending: headerAdvicePending,
    toggleStays: headerToggleStays,
    toggleFlights: headerToggleFlights,
    toggleIntel: headerToggleIntel,
  } = usePanelToggleStore(useShallow((s) => ({
    staysExpanded: s.staysExpanded,
    flightsExpanded: s.flightsExpanded,
    intelExpanded: s.intelExpanded,
    travelAdviceCount: s.travelAdviceCount,
    showTravelAdvice: s.showTravelAdvice,
    isTravelAdvicePending: s.isTravelAdvicePending,
    toggleStays: s.toggleStays,
    toggleFlights: s.toggleFlights,
    toggleIntel: s.toggleIntel,
  })));

  const headerFlightCount = useMemo(
    () => Object.values(tiles).filter((tile) => tile.type === 'flight').length,
    [tiles]
  );
  const headerStayCount = useMemo(
    () => Object.values(tiles).filter((tile) =>
      tile.type === 'hotel' || tile.type === 'stay' || tile.type === 'accommodation'
    ).length,
    [tiles]
  );

  return (
    <div className="flex w-full items-center min-w-0">
      <div className="flex items-center gap-2 shrink-0">
        <Compass className="text-emerald-600 dark:text-emerald-500 h-5 w-5" />
        <span className="text-zinc-900 dark:text-white text-lg font-semibold">Nomadic</span>
        {!showHeaderPills && (
          <span className="text-zinc-900 dark:text-white hidden xl:inline text-sm">
            <span className="text-zinc-400/30 dark:text-zinc-500/30 mx-2">|</span>
            Change your mind. Keep the plan.
          </span>
        )}
      </div>

      {showHeaderPills && tripInputs && (
        <div className="flex-1 min-w-0 flex justify-center px-3">
          <TripSummaryPills
            compact
            tripInputs={tripInputs}
            dayCards={dayCards}
            onOpenSheet={openSheet}
            disabled={isGenerating}
            flightCount={hasItineraryContent ? headerFlightCount : 0}
            stayCount={hasItineraryContent ? headerStayCount : 0}
            travelAdviceCount={headerAdviceCount}
            showTravelAdvice={headerShowAdvice}
            isTravelAdvicePending={headerAdvicePending}
            flightsActive={headerFlightsActive}
            staysActive={headerStaysActive}
            travelAdviceActive={headerIntelActive}
            onToggleFlights={headerToggleFlights}
            onToggleStays={headerToggleStays}
            onToggleTravelAdvice={headerToggleIntel}
          />
        </div>
      )}

      <div className="flex items-center gap-2 shrink-0 ml-auto">
        {user ? (
          <LandingHeaderUserMenu
            user={user}
            otherTrips={otherTrips}
            resumingTripId={resumingTripId}
            handleNewTrip={handleNewTrip}
            handleLogout={handleLogout}
            resumeTrip={resumeTrip}
            addToast={addToast}
          />
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleLogin}
            disabled={userLoading}
            className={cn(
              DS.textSize.micro,
              'font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-white disabled:pointer-events-none disabled:opacity-50'
            )}
          >
            {userLoading ? (
              <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
            ) : (
              <LogIn className="mr-1.5 h-3 w-3" />
            )}
            Sign in
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleStartNewSession}
          disabled={isResettingSession}
          className={cn(
            DS.textSize.micro,
            'font-bold uppercase tracking-widest text-zinc-500 dark:text-zinc-500 hover:bg-zinc-100 dark:hover:bg-white/5 hover:text-zinc-900 dark:hover:text-white disabled:pointer-events-none disabled:opacity-50'
          )}
        >
          {isResettingSession ? (
            <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
          ) : (
            <RotateCcw className="mr-1.5 h-3 w-3" />
          )}
          {isResettingSession ? 'Resetting' : 'Reset'}
        </Button>
      </div>
    </div>
  );
});
