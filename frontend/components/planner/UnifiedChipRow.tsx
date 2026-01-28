/**
 * UnifiedChipRow - "Cockpit" Layout
 *
 * Two-deck vertical layout for trip inputs. All controls above chat input.
 *
 * Layout:
 * ┌─────────────────────────────────────────────────────────────┐
 * │ DECK 1: [ Destination ] [ Origin ] [ Dates ] [ Travelers ] │  ← Context Pills (h-9, 36px)
 * │ DECK 2: [ Flights ] [ Stays ] [ Activities ]               │  ← Module Pills (h-10, 40px)
 * └─────────────────────────────────────────────────────────────┘
 *
 * Design Rules:
 * - Deck 1: h-9 tactile buttons, monochrome glass (grey → white when filled)
 * - Deck 2: h-10 primary touch targets, teal glow when active
 * - Vertical stack reads top-down: Context → Scope → Chat
 * - "Cockpit" aesthetic - all instruments large and readable
 */

'use client';

import {
  Calendar,
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
  /** If true, treat as "default value" - don't highlight even if has value */
  isDefault?: boolean;
}

const CoreChip = memo(function CoreChip({
  icon: Icon,
  label,
  value,
  onClick,
  isOptional,
  isDefault = false,
}: CoreChipProps) {
  const hasValue = !!value;
  // Only highlight if has user-set value (not default)
  const isHighlighted = hasValue && !isDefault;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        // Premium Standard: h-9 (36px) - tactile & readable
        'inline-flex items-center gap-2 h-9 px-3.5 rounded-lg',
        'transition-all duration-200 ease-out active:scale-[0.98]',
        'border',
        // Base state (unfilled) - Light: White card with grey border
        !isHighlighted && [
          'bg-white text-zinc-500 border-zinc-200',
          'hover:border-emerald-500/50 hover:text-emerald-600',
          // Dark: glass with subtle border
          'dark:bg-white/[0.05] dark:text-zinc-400 dark:border-white/[0.10]',
          'dark:hover:bg-white/[0.10] dark:hover:border-white/20 dark:hover:text-white',
        ],
        // Highlighted state (filled) - Light: Monochrome "Printed Label"
        // Data is neutral - facts don't need color emphasis
        isHighlighted && [
          'bg-zinc-100 text-zinc-900 border-zinc-300 shadow-sm',
          'hover:bg-zinc-200 hover:border-zinc-400',
          // Dark: brighter glass with white text
          'dark:bg-white/[0.10] dark:text-white dark:border-white/20',
          'dark:hover:bg-white/[0.15] dark:hover:border-white/30',
        ],
        // Focus ring
        'focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-emerald-500/40 dark:focus-visible:ring-white/20'
      )}
    >
      <Icon
        className={cn(
          'h-4 w-4 flex-shrink-0',
          // Light: dark grey when filled (monochrome), grey when empty
          isHighlighted ? 'text-zinc-700 dark:text-white' : 'text-zinc-400 dark:text-zinc-500'
        )}
      />
      <span className="text-xs font-semibold uppercase tracking-wide truncate max-w-[100px]">
        {value || label}
        {!value && isOptional && (
          <span className="text-[10px] opacity-50 ml-1 normal-case tracking-normal">(opt)</span>
        )}
      </span>
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
        // Premium Standard: h-10 (40px) - primary touch target
        'inline-flex items-center gap-2 h-10 px-5 rounded-full',
        'transition-all duration-200 ease-out active:scale-[0.95]',
        'border',
        // Off: Light: white card, Dark: ghost outline
        isOff && [
          'bg-white text-zinc-500 border-zinc-200',
          'hover:bg-zinc-50 hover:text-zinc-900',
          // Dark: ghost outline
          'dark:bg-transparent dark:text-zinc-500 dark:border-zinc-800',
          'dark:hover:border-zinc-700 dark:hover:text-zinc-400',
        ],
        // On Default: Pastel emerald "Highlighter" - tinted, not solid
        // Actions are colored but subtle - like a highlighter mark
        isOnDefault && [
          'bg-emerald-50 text-emerald-800 border-emerald-200 shadow-sm',
          'hover:bg-emerald-100 hover:border-emerald-300',
          // Dark: emerald glow
          'dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/50',
          'dark:shadow-[0_0_15px_-3px_rgba(16,185,129,0.2)]',
          'dark:hover:border-emerald-500/70 dark:hover:shadow-[0_0_20px_-3px_rgba(16,185,129,0.3)]',
        ],
        // On Custom: Slightly stronger pastel with indicator dot
        isOnCustom && [
          'bg-emerald-100 text-emerald-900 border-emerald-300 shadow-sm font-semibold',
          'hover:bg-emerald-200 hover:border-emerald-400',
          // Dark: stronger emerald glow
          'dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-500/70',
          'dark:shadow-[0_0_20px_-3px_rgba(16,185,129,0.3)]',
          'dark:hover:border-emerald-400 dark:hover:shadow-[0_0_25px_-3px_rgba(16,185,129,0.4)]',
        ],
        // Focus ring
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40'
      )}
    >
      <Icon className={cn(
        'h-5 w-5 flex-shrink-0',
        // Light: emerald when active (pastel bg), grey when off
        isOff ? 'text-zinc-400 dark:text-zinc-600' : 'text-emerald-700 dark:text-emerald-400'
      )} />
      <span className="text-sm font-medium">
        {label}
        {isOn && summary && (
          <span className="ml-1.5 text-xs opacity-75">· {summary}</span>
        )}
      </span>
      {/* Custom dot indicator */}
      {isOnCustom && (
        <span className="h-2 w-2 rounded-full bg-emerald-600 dark:bg-emerald-400" />
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

  // Check if travelers has been modified from default
  const isTravelersDefault = travelers === '1 adult';

  return (
    <div className="flex flex-col gap-4 w-full">
      {/* DECK 1: TRIP CONTEXT (The Facts) */}
      {/* Premium tactile buttons, monochrome, wraps naturally */}
      <div className="flex flex-wrap items-center gap-2">
        <CoreChip
          icon={MapPin}
          label="Destination"
          value={destination}
          onClick={onOpenDestination}
        />

        <CoreChip
          icon={Plane}
          label="Origin"
          value={origin}
          onClick={onOpenOrigin}
        />

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
          isDefault={isTravelersDefault}
        />

        <CoreChip
          icon={DollarSign}
          label="Budget"
          value={budget}
          onClick={onOpenBudget}
          isOptional
        />
      </div>

      {/* DECK 2: SCOPE TOGGLES (The Tools) */}
      {/* Premium touch targets, teal accents, highly clickable */}
      <div className="flex flex-wrap items-center gap-2.5">
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
