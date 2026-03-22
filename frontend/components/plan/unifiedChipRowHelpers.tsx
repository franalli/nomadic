/**
 * unifiedChipRowHelpers
 *
 * Extracted module-state derivation helpers and sub-components for UnifiedChipRow.
 */

import { Hotel, Plane, Ticket } from 'lucide-react';

import { cn } from '@/lib/utils';
import type { ActivitySettings, BookingTypes, FlightSettings, HotelSettings } from '@/types/document';
import { isBookingEnabled } from '@/types/document';

import type { ModuleState } from './ChipGroup';
import {
  getFlightChipSummary,
  getHotelChipSummary,
  isActivityCustom,
  isFlightCustom,
  isHotelCustom,
  ModuleChip,
} from './ChipGroup';

export function getFlightState(
  bookingTypes: BookingTypes,
  flightSettings?: FlightSettings
): ModuleState {
  if (!isBookingEnabled(bookingTypes.flights)) return 'off';
  return isFlightCustom(flightSettings) ? 'on-custom' : 'on-default';
}

export function getStaysState(
  bookingTypes: BookingTypes,
  hotelSettings?: HotelSettings
): ModuleState {
  if (!isBookingEnabled(bookingTypes.hotels)) return 'off';
  return isHotelCustom(hotelSettings) ? 'on-custom' : 'on-default';
}

export function getActivitiesState(
  bookingTypes: BookingTypes,
  activitySettings?: ActivitySettings,
  inferredActivityCategories?: string[]
): ModuleState {
  if (!isBookingEnabled(bookingTypes.activities)) return 'off';
  return isActivityCustom(activitySettings, inferredActivityCategories) ? 'on-custom' : 'on-default';
}

// ─────────────────────────────────────────────────────────────────────────────
// Booking modules row sub-component
// ─────────────────────────────────────────────────────────────────────────────

interface BookingModulesRowProps {
  isMobile: boolean;
  isBookingMode: boolean;
  flightState: ModuleState;
  staysState: ModuleState;
  activitiesState: ModuleState;
  flightSettings?: FlightSettings;
  hotelSettings?: HotelSettings;
  onOpenFlights?: () => void;
  onOpenStays?: () => void;
  onOpenActivities?: () => void;
}

export function BookingModulesRow({
  isMobile,
  isBookingMode,
  flightState,
  staysState,
  activitiesState,
  flightSettings,
  hotelSettings,
  onOpenFlights,
  onOpenStays,
  onOpenActivities,
}: BookingModulesRowProps) {
  return (
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
  );
}
