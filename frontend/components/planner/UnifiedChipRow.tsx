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

import { useMobileMode } from '@/contexts/MobileModeContext';
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
  /** Mobile mode - larger touch targets */
  isMobile?: boolean;
}

const CoreChip = memo(function CoreChip({
  icon: Icon,
  label,
  value,
  onClick,
  isOptional,
  isDefault = false,
  isMobile = false,
}: CoreChipProps) {
  const hasValue = !!value;
  // Only highlight if has user-set value (not default)
  const isHighlighted = hasValue && !isDefault;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        // Mobile: h-10 (40px) for better touch, Desktop: h-9 (36px)
        'inline-flex items-center gap-2 rounded-lg flex-shrink-0',
        isMobile ? 'h-10 px-4' : 'h-9 px-3.5',
        'transition-all duration-200 ease-out active:scale-[0.98]',
        'border',
        // Base state (unfilled) - Light: White card with grey border
        !isHighlighted && [
          'bg-white text-zinc-500 border-zinc-200',
          'hover:border-zinc-400 hover:text-zinc-900',
          // Dark: ghost with subtle border
          'dark:bg-transparent dark:text-zinc-400 dark:border-white/10',
          'dark:hover:border-white/30 dark:hover:text-white',
        ],
        // Highlighted state (filled) - Light: Strong zinc border "Printed Label"
        isHighlighted && [
          'bg-zinc-100 text-zinc-900 border-zinc-900 font-bold shadow-sm',
          'hover:bg-zinc-200',
          // Dark: white on transparent
          'dark:bg-white/10 dark:text-white dark:border-white/30',
          'dark:hover:bg-white/15',
        ],
        // Focus ring
        'focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-zinc-900/20 dark:focus-visible:ring-white/20'
      )}
    >
      <Icon
        className={cn(
          'h-4 w-4 flex-shrink-0',
          // Light: dark grey when filled (monochrome), grey when empty
          isHighlighted ? 'text-zinc-900 dark:text-white' : 'text-zinc-400 dark:text-zinc-500'
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
  /** Mobile mode - larger touch targets */
  isMobile?: boolean;
}

const ModuleChip = memo(function ModuleChip({
  icon: Icon,
  label,
  state,
  summary,
  onClick,
  isMobile = false,
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
        // Mobile: h-11 (44px) for Apple's minimum, Desktop: h-10 (40px)
        'inline-flex items-center gap-2 rounded-full flex-shrink-0',
        isMobile ? 'h-11 px-5' : 'h-10 px-5',
        'transition-all duration-200 ease-out active:scale-[0.95]',
        'border',
        // Off: Light: grey ghost, Dark: ghost outline
        isOff && [
          'bg-zinc-50 text-zinc-400 border-zinc-200',
          'hover:border-zinc-400 hover:text-zinc-600',
          // Dark: ghost outline
          'dark:bg-transparent dark:text-zinc-500 dark:border-white/10',
          'dark:hover:border-white/30 dark:hover:text-zinc-300',
        ],
        // On Default: Monochromatic - solid black/white
        isOnDefault && [
          'bg-zinc-900 text-white border-zinc-900 shadow-md',
          'hover:bg-zinc-800',
          // Dark: solid white
          'dark:bg-white dark:text-black dark:border-white',
          'dark:hover:bg-zinc-100',
        ],
        // On Custom: Same as default but with indicator dot
        isOnCustom && [
          'bg-zinc-900 text-white border-zinc-900 shadow-md font-semibold',
          'hover:bg-zinc-800',
          // Dark: solid white
          'dark:bg-white dark:text-black dark:border-white',
          'dark:hover:bg-zinc-100',
        ],
        // Focus ring
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20 dark:focus-visible:ring-white/30'
      )}
    >
      <Icon className={cn(
        'h-5 w-5 flex-shrink-0',
        // Monochrome icon colors
        isOff ? 'text-zinc-400 dark:text-zinc-500' : 'text-white dark:text-black'
      )} />
      <span className="text-sm font-medium">
        {label}
        {isOn && summary && (
          <span className="ml-1.5 text-xs opacity-75">· {summary}</span>
        )}
      </span>
      {/* Custom dot indicator - emerald to show customization */}
      {isOnCustom && (
        <span className="h-2 w-2 rounded-full bg-emerald-500 dark:bg-emerald-600" />
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
  const { isDesktop } = useMobileMode();
  const isMobile = !isDesktop;

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
    <div className="flex flex-col gap-3 w-full">
      {/* DECK 1: TRIP CONTEXT (The Facts) */}
      {/* Mobile: horizontal scroll reel, Desktop: wrap naturally */}
      <div className={cn(
        'flex items-center gap-2',
        // Mobile: horizontal scroll carousel
        isMobile && 'overflow-x-auto no-scrollbar -mx-4 px-4 py-1',
        // Desktop: natural wrap
        !isMobile && 'flex-wrap'
      )}>
        <CoreChip
          icon={MapPin}
          label="Destination"
          value={destination}
          onClick={onOpenDestination}
          isMobile={isMobile}
        />

        <CoreChip
          icon={Plane}
          label="Origin"
          value={origin}
          onClick={onOpenOrigin}
          isMobile={isMobile}
        />

        <CoreChip
          icon={Calendar}
          label="Dates"
          value={dateRange}
          onClick={onOpenDates}
          isMobile={isMobile}
        />

        <CoreChip
          icon={Users}
          label="Travelers"
          value={travelers}
          onClick={onOpenTravelers}
          isDefault={isTravelersDefault}
          isMobile={isMobile}
        />

        <CoreChip
          icon={DollarSign}
          label="Budget"
          value={budget}
          onClick={onOpenBudget}
          isOptional
          isMobile={isMobile}
        />
      </div>

      {/* DECK 2: SCOPE TOGGLES (The Tools) */}
      {/* Mobile: horizontal scroll reel, Desktop: wrap naturally */}
      <div className={cn(
        'flex items-center gap-2.5',
        // Mobile: horizontal scroll carousel
        isMobile && 'overflow-x-auto no-scrollbar -mx-4 px-4 py-1',
        // Desktop: natural wrap
        !isMobile && 'flex-wrap'
      )}>
        <ModuleChip
          icon={Plane}
          label="Flights"
          state={getFlightState()}
          summary={getFlightChipSummary(flightSettings)}
          onClick={onOpenFlights}
          isMobile={isMobile}
        />

        <ModuleChip
          icon={Hotel}
          label="Stays"
          state={getStaysState()}
          summary={getHotelChipSummary(hotelSettings)}
          onClick={onOpenStays}
          isMobile={isMobile}
        />

        <ModuleChip
          icon={Ticket}
          label="Activities"
          state={getActivitiesState()}
          summary={getActivityChipSummary(activitySettings)}
          onClick={onOpenActivities}
          isMobile={isMobile}
        />
      </div>
    </div>
  );
}

export const UnifiedChipRow = memo(UnifiedChipRowInner);

export default UnifiedChipRow;
