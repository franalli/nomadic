'use client';

/**
 * UnifiedChipRow - "Cockpit" Layout
 *
 * Three-row semantic layout for trip inputs. All controls above chat input.
 *
 * Layout:
 * +----------------------------------------------------+
 * | ROW 1: [ Destination ] [ Origin ] [ Dates ]        |  <- Trip params (h-8, 32px)
 * | ROW 2: [ Travelers ] [ Budget (opt) ]              |  <- Travelers   (h-8, 32px)
 * | ROW 3: [ Flights ] [ Stays ] [ Activities ]        |  <- Booking types (h-9, 36px)
 * +----------------------------------------------------+
 *
 * Design Rules:
 * - Row 1-2: h-8 compact pills, monochrome glass (grey -> white when filled)
 * - Row 3: h-9 primary touch targets, emerald glow when active
 * - Semantic grouping: "what you're planning" vs "what we'll search for"
 * - "Cockpit" aesthetic - all instruments readable at >=380px panel width
 */

import {
  Calendar,
  DollarSign,
  Hotel,
  MapPin,
  Plane,
  Ticket,
  Users,
} from 'lucide-react';
import { memo, useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { type ActivitySettings, type BookingTypes, type FlightSettings, type HotelSettings, isBookingEnabled } from '@/types/document';
import type { ViewMode } from '@/types/plan-envelope';

import type { ModuleState } from './ChipGroup';
import {
  getFlightChipSummary,
  getHotelChipSummary,
  inferCategoriesFromDayCards,
  isActivityCustom,
  isFlightCustom,
  isHotelCustom,
  ModuleChip,
  SetupCoreChip,
} from './ChipGroup';
import { ChipScrollContainer } from './ChipScrollContainer';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UnifiedChipRowProps {
  // Core values (Row A)
  destination?: string | null;
  origin?: string | null;
  dateRange?: string | null;
  travelers?: string | null;
  budget?: string | null;

  // Module state (Row B)
  bookingTypes: BookingTypes;
  flightSettings?: FlightSettings;
  hotelSettings?: HotelSettings;
  activitySettings?: ActivitySettings;

  // Sheet open handlers (core)
  onOpenDestination?: () => void;
  onOpenOrigin?: () => void;
  onOpenDates?: () => void;
  onOpenTravelers?: () => void;
  onOpenBudget?: () => void;

  // Sheet open handlers (modules)
  onOpenFlights?: () => void;
  onOpenStays?: () => void;
  onOpenActivities?: () => void;

  // Two-mode system support
  /** Current mode - chips are read-only in 'booking' mode */
  mode?: ViewMode;
  /** Lock destination chip - once set, can only change via full trip reset */
  destinationLocked?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

function UnifiedChipRowInner({
  // Core values
  destination,
  origin,
  dateRange,
  travelers = '1 adult', // Default per spec
  budget,
  // Module state
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  // Core handlers
  onOpenDestination,
  onOpenOrigin,
  onOpenDates,
  onOpenTravelers,
  onOpenBudget,
  // Module handlers
  onOpenFlights,
  onOpenStays,
  onOpenActivities,
  // Mode
  mode,
  destinationLocked,
}: UnifiedChipRowProps) {
  const isDesktop = useIsDesktop();
  const isMobile = !isDesktop;
  const dayCards = useDocumentStore(useShallow((s) => s.document?.day_cards));
  const inferredActivityCategories = useMemo(
    () => inferCategoriesFromDayCards(dayCards),
    [dayCards]
  );

  // In BOOKING mode, chips are read-only (show values but can't edit)
  const isBookingMode = mode === 'booking';

  // Determine module chip states (tri-state: suggested or on = enabled)
  const getFlightState = (): ModuleState => {
    if (!isBookingEnabled(bookingTypes.flights)) return 'off';
    return isFlightCustom(flightSettings) ? 'on-custom' : 'on-default';
  };

  const getStaysState = (): ModuleState => {
    if (!isBookingEnabled(bookingTypes.hotels)) return 'off';
    return isHotelCustom(hotelSettings) ? 'on-custom' : 'on-default';
  };

  const getActivitiesState = (): ModuleState => {
    if (!isBookingEnabled(bookingTypes.activities)) return 'off';
    return isActivityCustom(activitySettings, inferredActivityCategories) ? 'on-custom' : 'on-default';
  };
  const flightState = getFlightState();
  const staysState = getStaysState();
  const activitiesState = getActivitiesState();

  // Check if travelers has been modified from default
  const isTravelersDefault = travelers === '1 adult';

  // Budget: always visible in setup/landing — progressive discovery only in itinerary view
  const isBudgetDefault = !budget;

  return (
    <div className="flex flex-col gap-2 w-full">
      {/* MOBILE ROW 1: TRIP PARAMS (Where & When) */}
      {/* DESKTOP ROW 1: All 5 core chips on one line (no-wrap, scrollable if needed) */}
      {isMobile ? (
        <ChipScrollContainer scroll>
          <SetupCoreChip icon={MapPin} label="Destination" value={destination} onClick={destinationLocked ? undefined : onOpenDestination} isMobile disabled={isBookingMode} />
          <SetupCoreChip icon={Plane} label="Origin" value={origin} onClick={onOpenOrigin} isMobile disabled={isBookingMode} />
          <SetupCoreChip icon={Calendar} label="Dates" value={dateRange} onClick={onOpenDates} isMobile disabled={isBookingMode} />
          <SetupCoreChip icon={Users} label="Travelers" value={travelers} onClick={onOpenTravelers} isDefault={isTravelersDefault} isMobile disabled={isBookingMode} />
          <SetupCoreChip icon={DollarSign} label="Budget" value={budget} onClick={onOpenBudget} isDefault={isBudgetDefault} isMobile={isMobile} disabled={isBookingMode} />
        </ChipScrollContainer>
      ) : (
        /* Desktop: single row, centered. Parent ChatMessageList uses overflow-x-clip + -mx-4 px-4
           so the clip boundary is the full panel width - chips won't get cut. */
        <ChipScrollContainer>
          <SetupCoreChip icon={MapPin} label="Destination" value={destination} onClick={destinationLocked ? undefined : onOpenDestination} disabled={isBookingMode} />
          <SetupCoreChip icon={Plane} label="Origin" value={origin} onClick={onOpenOrigin} disabled={isBookingMode} />
          <SetupCoreChip icon={Calendar} label="Dates" value={dateRange} onClick={onOpenDates} disabled={isBookingMode} />
          <SetupCoreChip icon={Users} label="Travelers" value={travelers} onClick={onOpenTravelers} isDefault={isTravelersDefault} disabled={isBookingMode} />
          <SetupCoreChip icon={DollarSign} label="Budget" value={budget} onClick={onOpenBudget} isDefault={isBudgetDefault} disabled={isBookingMode} />
        </ChipScrollContainer>
      )}

      {/* MOBILE ROW 2: TRAVELERS (separate row on mobile only) */}
      {isMobile && (
        <ChipScrollContainer scroll>
          <SetupCoreChip
            icon={Users}
            label="Travelers"
            value={travelers}
            onClick={onOpenTravelers}
            isDefault={isTravelersDefault}
            isMobile={isMobile}
            disabled={isBookingMode}
          />

          <SetupCoreChip
            icon={DollarSign}
            label="Budget"
            value={budget}
            onClick={onOpenBudget}
            isDefault={isBudgetDefault}
            isMobile={isMobile}
            disabled={isBookingMode}
          />
        </ChipScrollContainer>
      )}

      {/* ROW 3: BOOKING TYPES (What We Search For) */}
      <div className={cn(
        'flex items-center gap-2',
        isMobile && 'overflow-x-auto no-scrollbar -mx-4 px-4 py-1',
        !isMobile && 'flex-wrap justify-center py-0.5'
      )}>
        <ModuleChip
          icon={Plane}
          label="Flights"
          state={flightState}
          summary={getFlightChipSummary(flightSettings)}
          onClick={onOpenFlights}
          isMobile={isMobile}
          disabled={isBookingMode}
          showCompletionCheckWhenOn={false}
        />

        <ModuleChip
          icon={Hotel}
          label="Stays"
          state={staysState}
          summary={getHotelChipSummary(hotelSettings)}
          onClick={onOpenStays}
          isMobile={isMobile}
          disabled={isBookingMode}
          showCompletionCheckWhenOn={false}
        />

        <ModuleChip
          icon={Ticket}
          label="Activities"
          badge={undefined}
          state={activitiesState}
          summary={null}
          onClick={onOpenActivities}
          isMobile={isMobile}
          disabled={isBookingMode}
          showCompletionCheckWhenOn={false}
        />
      </div>
    </div>
  );
}

export const UnifiedChipRow = memo(UnifiedChipRowInner);

export default UnifiedChipRow;
