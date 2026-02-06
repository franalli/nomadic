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
  Check,
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
import type { ViewMode } from '@/types/plan-envelope';

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

  // Two-mode system support
  /** Current mode - chips are read-only in 'booking' mode */
  mode?: ViewMode;
  /** Lock destination chip - once set, can only change via full trip reset */
  destinationLocked?: boolean;
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
  /** Disabled state (e.g., in BOOKING mode) */
  disabled?: boolean;
}

const CoreChip = memo(function CoreChip({
  icon: Icon,
  label,
  value,
  onClick,
  isOptional,
  isDefault = false,
  isMobile = false,
  disabled = false,
}: CoreChipProps) {
  const hasValue = !!value;
  // Only highlight if has user-set value (not default)
  const isSet = hasValue && !isDefault;

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={cn(
        // Mobile: h-10 (40px) for better touch, Desktop: h-9 (36px)
        'inline-flex items-center gap-2 rounded-lg flex-shrink-0 cursor-pointer',
        isMobile ? 'h-10 px-4' : 'h-9 px-3.5',
        'transition-all duration-200 ease-out active:scale-[0.98]',
        // Hover: Scale 1.02 + snap-to-black/white (DS Tactile Rule)
        'hover:scale-[1.02] hover:border-zinc-900',
        // Dark hover: emerald accent per DS "Bioluminescent" aesthetic
        'dark:hover:border-emerald-500/50',

        // --- STATE: SET (has user value) ---
        // DS Section 3: Active pills use maximum contrast (zinc-900 light / white dark)
        isSet && [
          // Background: Very subtle grey
          'bg-zinc-50',
          // Border: Zinc-900 at 30% opacity (per DS - not blue)
          'border border-zinc-900/30',
          // Text: Near-black
          'text-zinc-900 font-semibold',
          // Shadow for "lifted" feel
          'shadow-sm',
          // Dark mode: Glass Fill with emerald accent
          'dark:bg-white/10 dark:text-white dark:border-emerald-500/30',
          'dark:hover:bg-white/15',
        ],

        // --- STATE: OPTIONAL (unset, optional field) ---
        !isSet && isOptional && [
          // Background: Transparent
          'bg-transparent',
          // Border: Dashed, very light
          'border border-dashed border-zinc-200',
          // Text: Muted
          'text-zinc-400',
          // Dark mode
          'dark:border-white/10 dark:text-zinc-500',
          'dark:hover:border-white/30 dark:hover:text-zinc-300',
        ],

        // --- STATE: UNSET REQUIRED (no value, required field) ---
        !isSet && !isOptional && [
          // Background: Transparent
          'bg-transparent',
          // Border: Solid, subtle grey
          'border border-zinc-200',
          // Text: Muted grey
          'text-zinc-400',
          // Dark mode
          'dark:bg-white/5 dark:text-zinc-500 dark:border-white/10',
          'dark:hover:border-white/30 dark:hover:text-white',
        ],

        // Focus ring - zinc light / emerald dark per DS
        'focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/20',

        // --- STATE: DISABLED (BOOKING mode) ---
        disabled && [
          'opacity-60 cursor-not-allowed',
          'hover:scale-100 hover:border-current', // Disable hover effects
        ]
      )}
    >
      <Icon
        className={cn(
          'h-4 w-4 flex-shrink-0',
          // Icon color based on state - DS accent colors (zinc/emerald, not blue)
          isSet
            ? 'text-zinc-900 dark:text-emerald-400'
            : 'text-zinc-400 dark:text-zinc-500',
          disabled && 'opacity-60'
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
  /** Disabled state (e.g., in BOOKING mode) */
  disabled?: boolean;
}

const ModuleChip = memo(function ModuleChip({
  icon: Icon,
  label,
  state,
  summary,
  onClick,
  isMobile = false,
  disabled = false,
}: ModuleChipProps) {
  const isOff = state === 'off';
  const isOnDefault = state === 'on-default';
  const isOnCustom = state === 'on-custom';
  const isOn = isOnDefault || isOnCustom;

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={cn(
        // Mobile: h-11 (44px) for Apple's minimum, Desktop: h-10 (40px)
        'inline-flex items-center gap-2 rounded-full flex-shrink-0',
        isMobile ? 'h-11 px-5' : 'h-10 px-5',
        'transition-all duration-200 ease-out active:scale-[0.95]',
        'border',

        // --- STATE: OFF (inactive) ---
        isOff && [
          // Transparent background
          'bg-transparent',
          // Grey border
          'border-zinc-200',
          // Grey text
          'text-zinc-400',
          // Hover: border darkens
          'hover:border-zinc-400 hover:text-zinc-600',
          // Dark mode
          'dark:border-white/10 dark:text-zinc-500',
          'dark:hover:border-white/30 dark:hover:text-zinc-300',
        ],

        // --- STATE: ON (active - default or custom) ---
        // DS Section 3: Active pills = maximum contrast
        isOn && [
          // Solid white background
          'bg-white',
          // Zinc-900 border for active state (DS - not blue)
          'border-zinc-900',
          // Dark text
          'text-zinc-900 font-medium',
          // Subtle shadow
          'shadow-sm',
          // Hover
          'hover:bg-zinc-50 hover:shadow-md',
          // Dark mode: invert - solid white per DS pills.active
          'dark:bg-white dark:text-black dark:border-white',
          'dark:hover:bg-zinc-100',
        ],

        // Focus ring - zinc light / emerald dark per DS
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/30',

        // --- STATE: DISABLED (BOOKING mode) ---
        disabled && 'opacity-60 cursor-not-allowed hover:shadow-sm'
      )}
    >
      {/* Checkmark for active state (replaces icon position) */}
      {/* DS: zinc-900 light / emerald dark for accent elements */}
      {isOn ? (
        <Check className="h-4 w-4 flex-shrink-0 text-zinc-900 dark:text-emerald-500" strokeWidth={2.5} />
      ) : (
        <Icon className="h-5 w-5 flex-shrink-0 text-zinc-400 dark:text-zinc-500" />
      )}
      <span className="text-sm">
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
  // Mode
  mode,
  destinationLocked,
}: UnifiedChipRowProps) {
  const { isDesktop } = useMobileMode();
  const isMobile = !isDesktop;

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
          onClick={destinationLocked ? undefined : onOpenDestination}
          isMobile={isMobile}
          disabled={isBookingMode}
        />

        <CoreChip
          icon={Plane}
          label="Origin"
          value={origin}
          onClick={onOpenOrigin}
          isMobile={isMobile}
          disabled={isBookingMode}
        />

        <CoreChip
          icon={Calendar}
          label="Dates"
          value={dateRange}
          onClick={onOpenDates}
          isMobile={isMobile}
          disabled={isBookingMode}
        />

        <CoreChip
          icon={Users}
          label="Travelers"
          value={travelers}
          onClick={onOpenTravelers}
          isDefault={isTravelersDefault}
          isMobile={isMobile}
          disabled={isBookingMode}
        />

        <CoreChip
          icon={DollarSign}
          label="Budget"
          value={budget}
          onClick={onOpenBudget}
          isOptional
          isMobile={isMobile}
          disabled={isBookingMode}
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
          disabled={isBookingMode}
        />

        <ModuleChip
          icon={Hotel}
          label="Stays"
          state={getStaysState()}
          summary={getHotelChipSummary(hotelSettings)}
          onClick={onOpenStays}
          isMobile={isMobile}
          disabled={isBookingMode}
        />

        <ModuleChip
          icon={Ticket}
          label="Activities"
          state={getActivitiesState()}
          summary={getActivityChipSummary(activitySettings)}
          onClick={onOpenActivities}
          isMobile={isMobile}
          disabled={isBookingMode}
        />
      </div>
    </div>
  );
}

export const UnifiedChipRow = memo(UnifiedChipRowInner);

export default UnifiedChipRow;
