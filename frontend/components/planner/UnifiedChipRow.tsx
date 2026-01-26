/**
 * UnifiedChipRow
 *
 * Two-row chip layout for all trip constraints.
 * Single entry point for all inputs - replaces OnboardingChips + OptionalRefinementsSection.
 *
 * Layout:
 * Row A (core):    [ Destination ] [ Origin* ] [ Dates ] [ Travelers ] [ Budget ]
 * Row B (modules): [ Flights ] [ Stays ] [ Activities ]
 *
 * * Origin only visible when Flights module is ON
 *
 * Chip states:
 * - Core chips: unset (muted) → set (highlighted with value)
 * - Module chips: off (muted) → on-default (subtle) → on-custom (highlight + dot)
 */

'use client';

import {
  Calendar,
  Check,
  DollarSign,
  Hotel,
  MapPin,
  Plane,
  Ticket,
  Users,
} from 'lucide-react';
import { memo } from 'react';

import { cn } from '@/lib/utils';
import { type ActivitySettings,type BookingTypes, type FlightSettings, type HotelSettings, isBookingEnabled } from '@/types/document';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export interface UnifiedChipRowProps {
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
}

// ─────────────────────────────────────────────────────────────────────────────
// Chip Defaults (for detecting "custom" state)
// ─────────────────────────────────────────────────────────────────────────────

const isFlightCustom = (settings?: FlightSettings): boolean => {
  if (!settings) return false;
  return (
    settings.cabin_class !== 'economy' ||
    settings.direct_only === true ||
    settings.round_trip === false
  );
};

const isHotelCustom = (settings?: HotelSettings): boolean => {
  if (!settings) return false;
  return (
    (settings.min_stars !== undefined && settings.min_stars > 0) ||
    (settings.amenities !== undefined && settings.amenities.length > 0)
  );
};

const isActivityCustom = (settings?: ActivitySettings): boolean => {
  if (!settings) return false;
  return settings.categories !== undefined && settings.categories.length > 0;
};

// ─────────────────────────────────────────────────────────────────────────────
// Chip Summary Helpers
// ─────────────────────────────────────────────────────────────────────────────

function getFlightChipSummary(settings?: FlightSettings): string | null {
  if (!settings) return null;

  const tokens: string[] = [];

  // Stops: only if constrained
  if (settings.direct_only) {
    tokens.push('Nonstop');
  }

  // Cabin: only if not economy
  if (settings.cabin_class && settings.cabin_class !== 'economy') {
    const cabinLabels: Record<string, string> = {
      premium_economy: 'Premium',
      business: 'Business',
      first: 'First',
    };
    tokens.push(cabinLabels[settings.cabin_class] || settings.cabin_class);
  }

  // One-way: only if one-way
  if (settings.round_trip === false) {
    tokens.push('One-way');
  }

  // Max 2 tokens
  return tokens.slice(0, 2).join(' · ') || null;
}

function getHotelChipSummary(settings?: HotelSettings): string | null {
  if (!settings) return null;

  const tokens: string[] = [];

  if (settings.min_stars && settings.min_stars > 0) {
    tokens.push(`${settings.min_stars}★+`);
  }

  // Could add area/location if available in settings

  return tokens.slice(0, 2).join(' · ') || null;
}

function getActivityChipSummary(settings?: ActivitySettings): string | null {
  if (!settings || !settings.categories || settings.categories.length === 0) {
    return null;
  }

  // Max 2 categories
  const categories = settings.categories.slice(0, 2);
  return categories.map(c => c.charAt(0).toUpperCase() + c.slice(1)).join(' · ');
}

// ─────────────────────────────────────────────────────────────────────────────
// Core Chip Component (Row A)
// ─────────────────────────────────────────────────────────────────────────────

interface CoreChipProps {
  icon: typeof MapPin;
  label: string;
  value?: string | null;
  onClick?: () => void;
  isOptional?: boolean;
}

const CoreChip = memo(function CoreChip({
  icon: Icon,
  label,
  value,
  onClick,
  isOptional,
}: CoreChipProps) {
  const hasValue = !!value;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        // Base chip styling (h-7 = 28px)
        'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full',
        'transition-all duration-[120ms] ease-out active:scale-[0.98]',
        // State-based styling
        hasValue
          ? 'border border-[var(--chip-active-border)] bg-[var(--chip-active-bg)] text-[var(--chip-active-text)] font-semibold'
          : 'border border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
        // Hover states
        !hasValue && 'hover:border-[var(--chip-border-hover)]',
        hasValue && 'hover:border-[var(--chip-active-border)]',
        // Focus ring
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--chip-active-icon)]/50'
      )}
    >
      <Icon
        className={cn(
          'h-3.5 w-3.5 flex-shrink-0',
          hasValue ? 'text-[var(--chip-active-icon)]' : ''
        )}
      />
      <span className="text-xs truncate max-w-[120px]">
        {value || label}
        {!value && isOptional && (
          <span className="text-[10px] text-zinc-400 dark:text-zinc-600 ml-1">(opt)</span>
        )}
      </span>
      {hasValue && <Check className="h-2.5 w-2.5 text-[var(--chip-active-icon)]" />}
    </button>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
// Module Chip Component (Row B) - 3-state: off → on-default → on-custom
// ─────────────────────────────────────────────────────────────────────────────

type ModuleState = 'off' | 'on-default' | 'on-custom';

interface ModuleChipProps {
  icon: typeof Plane;
  label: string;
  state: ModuleState;
  summary?: string | null;
  onClick?: () => void;
}

const ModuleChip = memo(function ModuleChip({
  icon: Icon,
  label,
  state,
  summary,
  onClick,
}: ModuleChipProps) {
  const isOff = state === 'off';
  const isOnDefault = state === 'on-default';
  const isOnCustom = state === 'on-custom';
  const isOn = isOnDefault || isOnCustom;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        // Base chip styling
        'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full',
        'transition-all duration-[120ms] ease-out active:scale-[0.98]',
        // 3-state styling
        isOff && [
          'border border-[var(--chip-border)] bg-[var(--chip-bg)] text-[var(--chip-text)]',
          'opacity-70 hover:opacity-100 hover:border-[var(--chip-border-hover)]',
        ],
        isOnDefault && [
          'border border-teal-500/30 bg-teal-500/10 text-teal-600 dark:text-teal-400',
          'hover:border-teal-500/50',
        ],
        isOnCustom && [
          'border border-teal-500/50 bg-teal-500/15 text-teal-600 dark:text-teal-400 font-semibold',
          'hover:border-teal-500/70',
        ],
        // Focus ring
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-teal-500/50'
      )}
    >
      <Icon className="h-3.5 w-3.5 flex-shrink-0" />
      <span className="text-xs truncate max-w-[120px]">
        {label}
        {isOn && summary && (
          <span className="ml-1 text-[10px] opacity-80">· {summary}</span>
        )}
      </span>
      {/* Custom dot indicator */}
      {isOnCustom && (
        <span className="h-1.5 w-1.5 rounded-full bg-teal-500" />
      )}
    </button>
  );
});

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
}: UnifiedChipRowProps) {
  // Determine if Origin should be visible (only when Flights ON - tri-state check)
  const showOrigin = isBookingEnabled(bookingTypes.flights);

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
    return isActivityCustom(activitySettings) ? 'on-custom' : 'on-default';
  };

  return (
    <div className="flex flex-col gap-2">
      {/* Row A: Core constraints */}
      <div className="flex flex-wrap gap-2">
        <CoreChip
          icon={MapPin}
          label="Destination"
          value={destination}
          onClick={onOpenDestination}
        />

        {/* Origin: Only visible when Flights ON */}
        {showOrigin && (
          <CoreChip
            icon={Plane}
            label="Origin"
            value={origin}
            onClick={onOpenOrigin}
          />
        )}

        <CoreChip
          icon={Calendar}
          label="Dates"
          value={dateRange}
          onClick={onOpenDates}
        />

        <CoreChip
          icon={Users}
          label="Travelers"
          value={travelers}
          onClick={onOpenTravelers}
        />

        <CoreChip
          icon={DollarSign}
          label="Budget"
          value={budget}
          onClick={onOpenBudget}
          isOptional
        />
      </div>

      {/* Row B: Module toggles */}
      <div className="flex flex-wrap gap-2">
        <ModuleChip
          icon={Plane}
          label="Flights"
          state={getFlightState()}
          summary={getFlightChipSummary(flightSettings)}
          onClick={onOpenFlights}
        />

        <ModuleChip
          icon={Hotel}
          label="Stays"
          state={getStaysState()}
          summary={getHotelChipSummary(hotelSettings)}
          onClick={onOpenStays}
        />

        <ModuleChip
          icon={Ticket}
          label="Activities"
          state={getActivitiesState()}
          summary={getActivityChipSummary(activitySettings)}
          onClick={onOpenActivities}
        />
      </div>
    </div>
  );
}

export const UnifiedChipRow = memo(UnifiedChipRowInner);

export default UnifiedChipRow;
