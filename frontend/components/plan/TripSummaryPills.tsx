/**
 * TripSummaryPills
 *
 * Compact pill row for displaying and editing trip constraints in the header.
 * This is the ONLY interactive trip input surface in Plan mode (S1+).
 *
 * Reads tripInputs and computes display values internally.
 * All formatting is done here, not passed as props.
 */

'use client';

import { Calendar, DollarSign, MapPin, Plane, Users } from 'lucide-react';

import { CoreChip } from '@/components/planner/CoreChip';
import {
  formatBudgetForPills,
  formatDateRangeForPills,
  formatTravelersForPills,
} from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import { DEFAULT_BOOKING_TYPES } from '@/state/documentStore';
import { type DocumentTripInputs,isBookingEnabled } from '@/types/document';
import type { SheetType } from '@/types/sheets';

interface TripSummaryPillsProps {
  tripInputs: DocumentTripInputs;
  onOpenSheet: (sheet: SheetType) => void;
  disabled?: boolean; // Disable all pills during streaming/generation
  /** Use 'onImage' when pills are on hero/photo background */
  variant?: 'default' | 'onImage';
}

export function TripSummaryPills({
  tripInputs,
  onOpenSheet,
  disabled = false,
  variant = 'default',
}: TripSummaryPillsProps) {
  // Read booking_types from tripInputs with safe fallback for fresh/migrating docs
  const bookingTypes = tripInputs.booking_types ?? DEFAULT_BOOKING_TYPES;

  // Compute display values
  const destination = tripInputs.destination || null;
  const origin = tripInputs.origin || null;
  const dateRange = formatDateRangeForPills(
    tripInputs.start_date,
    tripInputs.end_date
  );
  const travelers = formatTravelersForPills(
    tripInputs.adults,
    tripInputs.children
  );
  const budget = formatBudgetForPills(tripInputs.budget, tripInputs.currency);

  // Origin visibility: show when flights enabled OR origin already set
  const showOrigin = isBookingEnabled(bookingTypes.flights) || !!origin;

  return (
    <div
      className={cn(
        'flex gap-1.5 flex-wrap'
      )}
    >
      <CoreChip
        icon={MapPin}
        label="Destination"
        value={destination}
        placeholder="Add destination"
        tone={destination ? 'default' : 'missing'}
        onClick={() => onOpenSheet('destination')}
        disabled={disabled}
        variant={variant}
      />

      {showOrigin && (
        <CoreChip
          icon={Plane}
          label="Origin"
          value={origin}
          placeholder="Add origin"
          tone={origin ? 'default' : 'optional'}
          onClick={() => onOpenSheet('origin')}
          disabled={disabled}
          variant={variant}
        />
      )}

      <CoreChip
        icon={Calendar}
        label="Dates"
        value={dateRange}
        placeholder="Add dates"
        tone={dateRange ? 'default' : 'missing'}
        onClick={() => onOpenSheet('dates')}
        disabled={disabled}
        variant={variant}
      />

      <CoreChip
        icon={Users}
        label="Travelers"
        value={travelers}
        placeholder="1 adult"
        tone="default"
        onClick={() => onOpenSheet('travelers')}
        disabled={disabled}
        variant={variant}
      />

      <CoreChip
        icon={DollarSign}
        label="Budget"
        value={budget}
        placeholder="Budget (optional)"
        tone="optional"
        onClick={() => onOpenSheet('budget')}
        disabled={disabled}
        variant={variant}
      />
    </div>
  );
}

export default TripSummaryPills;
