'use client';

import { Compass, Loader2, LogIn, LogOut, Plus, RotateCcw } from 'lucide-react';
import { memo, useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { ToastType } from '@/components/ui/toast';
import { UserAvatar } from '@/components/ui/UserAvatar';
import { DS } from '@/lib/design-system';
import { cn, formatDateForDisplay } from '@/lib/utils';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { AuthUser, UserTripSummary } from '@/state/userStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

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
  // Read toggle states from shared store for header pills
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

  // Compute flight/stay counts for header pills (same logic as PlanFullDensityView)
  const headerFlightCount = useMemo(
    () => Object.values(tiles).filter(t => t.type === 'flight').length,
    [tiles]
  );
  const headerStayCount = useMemo(
    () => Object.values(tiles).filter(t =>
      t.type === 'hotel' || t.type === 'stay' || t.type === 'accommodation'
    ).length,
    [tiles]
  );

  return (
    <div className="flex w-full items-center min-w-0">
      {/* Left zone: logo + tagline */}
      <div className="flex items-center gap-2 shrink-0">
        <Compass className="text-primary h-5 w-5" />
        <span className="text-foreground text-lg font-semibold">Nomadic</span>
        {!showHeaderPills && (
          <span className="text-foreground hidden xl:inline text-sm">
            <span className="text-muted-foreground/30 mx-2">|</span>
            Change your mind. Keep the plan.
          </span>
        )}
      </div>

      {/* Pills zone: fills available space between logo and actions */}
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

      {/* Right zone: auth + reset */}
      <div className="flex items-center gap-2 shrink-0 ml-auto">
        {user ? (
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center overflow-hidden rounded-full border border-zinc-300 dark:border-white/15 bg-zinc-100 dark:bg-white/10"
                aria-label="User menu"
              >
                <UserAvatar
                  src={user.avatar_url}
                  alt={user.name || user.email}
                  imageClassName="h-full w-full object-cover"
                  iconClassName="h-4 w-4 text-zinc-600 dark:text-zinc-300"
                />
              </button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              className={cn('w-[280px] p-2', DS.materials.glass)}
            >
              <div className="px-2 py-1.5 border-b border-border mb-2">
                <p className="text-sm font-medium text-foreground truncate">{user.name || user.email}</p>
                <p className="text-xs text-muted-foreground truncate">{user.email}</p>
              </div>
              <div className="px-2 pb-2">
                <p className="text-xs font-medium uppercase tracking-widest text-muted-foreground mb-2">
                  Recent Trips
                </p>
                {otherTrips.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No saved trips yet.</p>
                ) : (
                  <div className="space-y-1.5">
                    {otherTrips.slice(0, 5).map((trip) => {
                      const isPast = trip.end_date && new Date(trip.end_date) < new Date();
                      return (
                        <button
                          key={`${trip.trip_id}-${trip.updated_at}`}
                          type="button"
                          disabled={resumingTripId !== null}
                          onClick={async () => {
                            const ok = await resumeTrip(trip.trip_id);
                            if (!ok) addToast('Could not open saved trip', 'error');
                          }}
                          className={cn(
                            'w-full rounded-lg px-2 py-1.5 text-left transition-colors outline-none focus-visible:ring-1 focus-visible:ring-white/20 hover:bg-white/[0.06] disabled:pointer-events-none disabled:opacity-50',
                            isPast && 'opacity-60'
                          )}
                        >
                          <p className="text-xs font-medium text-foreground truncate">
                            {trip.destination || 'Untitled Trip'}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {resumingTripId === trip.trip_id
                              ? 'Opening...'
                              : trip.start_date && trip.end_date
                              ? `${formatDateForDisplay(trip.start_date)} - ${formatDateForDisplay(trip.end_date)}${isPast ? ' (Past)' : ''}`
                              : 'Dates not set'}
                          </p>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={handleNewTrip}
                className="w-full inline-flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-foreground outline-none focus-visible:ring-1 focus-visible:ring-white/20 hover:bg-white/[0.06] transition-colors"
              >
                <Plus className="h-4 w-4" />
                New Trip
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="w-full inline-flex items-center gap-2 rounded-lg px-2 py-2 text-sm text-foreground outline-none focus-visible:ring-1 focus-visible:ring-white/20 hover:bg-white/[0.06] transition-colors"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </PopoverContent>
          </Popover>
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleLogin}
            disabled={userLoading}
            className={cn(
              DS.textSize.micro,
              'font-bold uppercase tracking-widest text-muted-foreground hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-50'
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
            'font-bold uppercase tracking-widest text-muted-foreground hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-50'
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
