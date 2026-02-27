'use client';

/**
 * UnifiedChipRow - "Cockpit" Layout
 *
 * Three-row semantic layout for trip inputs. All controls above chat input.
 *
 * Layout:
 * ┌──────────────────────────────────────────────────┐
 * │ ROW 1: [ Destination ] [ Origin ] [ Dates ]      │  ← Trip params (h-8, 32px)
 * │ ROW 2: [ Travelers ] [ Budget (opt) ]             │  ← Travelers   (h-8, 32px)
 * │ ROW 3: [ Flights ] [ Stays ] [ Activities ]       │  ← Booking types (h-9, 36px)
 * └──────────────────────────────────────────────────┘
 *
 * Design Rules:
 * - Row 1-2: h-8 compact pills, monochrome glass (grey → white when filled)
 * - Row 3: h-9 primary touch targets, emerald glow when active
 * - Semantic grouping: "what you're planning" vs "what we'll search for"
 * - "Cockpit" aesthetic - all instruments readable at ≥380px panel width
 */

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
import { memo, useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useDocumentStore } from '@/state/documentStore';
import { type ActivitySettings,type BookingTypes, type FlightSettings, type HotelSettings, isBookingEnabled } from '@/types/document';
import type { DayBlock, DayCard, ViewMode } from '@/types/plan-envelope';

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

const isActivityCustom = (
  settings?: ActivitySettings,
  fallbackCategories: string[] = []
): boolean => {
  if (!settings) return fallbackCategories.length > 0;
  const categories = settings.categories && settings.categories.length > 0 ? settings.categories : fallbackCategories;
  return categories.length > 0;
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

  return tokens.join(' · ') || null;
}

function getHotelChipSummary(settings?: HotelSettings): string | null {
  if (!settings) return null;

  const tokens: string[] = [];

  if (settings.min_stars && settings.min_stars > 0) {
    tokens.push(`${settings.min_stars}★+`);
  }

  // Include amenity filters
  if (settings.amenities && settings.amenities.length > 0) {
    const amenityLabels: Record<string, string> = {
      wifi: 'WiFi',
      pool: 'Pool',
      parking: 'Parking',
      gym: 'Gym',
      spa: 'Spa',
      breakfast: 'Breakfast',
      pet_friendly: 'Pets OK',
      beachfront: 'Beachfront',
    };
    for (const a of settings.amenities) {
      tokens.push(amenityLabels[a] || a.charAt(0).toUpperCase() + a.slice(1));
    }
  }

  if (tokens.length === 0) return null;
  if (tokens.length <= 4) return tokens.join(' · ');
  return `${tokens.slice(0, 2).join(' · ')} +${tokens.length - 2}`;
}

function getActivitySelectedCount(
  settings?: ActivitySettings,
  fallbackCategories: string[] = []
): number {
  const categoriesRaw = settings?.categories && settings.categories.length > 0
    ? settings.categories
    : fallbackCategories;
  if (categoriesRaw.length === 0) {
    return 0;
  }

  const normalized = categoriesRaw
    .map((category) => canonicalCategoryKey(category) ?? category.trim().toLowerCase())
    .filter((category): category is string => !!category);

  return Array.from(new Set(normalized)).length;
}

const NON_ACTIVITY_TYPES = new Set([
  'arrival', 'departure', 'check-in', 'check-out', 'check_in', 'check_out',
  'free_day', 'rest_day', 'buffer', 'decompression_buffer',
]);

const CATEGORY_ALIAS: Record<string, string> = {
  culture: 'cultural',
  tours: 'tours',
  attraction: 'tours',
  tourist_attraction: 'tours',
  point_of_interest: 'tours',
  travel_agency: 'tours',
  cultural_attraction: 'cultural',
  museum: 'cultural',
  art_gallery: 'cultural',
  historical_landmark: 'cultural',
  cultural_landmark: 'cultural',
  monument: 'cultural',
  plaza: 'cultural',
  ruins: 'cultural',
  fountain: 'cultural',
  hindu_temple: 'temples',
  temple: 'temples',
  church: 'cultural',
  place_of_worship: 'cultural',
  synagogue: 'cultural',
  mosque: 'cultural',
  restaurant: 'food',
  cafe: 'food',
  bar: 'food',
  bakery: 'food',
  meal_takeaway: 'food',
  meal_delivery: 'food',
  park: 'nature',
  natural_feature: 'nature',
  national_park: 'nature',
  campground: 'nature',
  zoo: 'nature',
  botanical_garden: 'nature',
  shopping_mall: 'shopping',
  market: 'shopping',
  store: 'shopping',
  clothing_store: 'shopping',
  department_store: 'shopping',
  beauty_salon: 'spa',
  gym: 'spa',
};

const TIER1_CONSTRAINT_HINTS: Record<string, RegExp[]> = {
  diving: [/\bdiv(e|ing|er|es)\b/i, /\bscuba\b/i, /\bno[- ]fly\b/i, /\bdecompression\b/i],
  hiking: [/\bhik(e|ing)\b/i, /\btrek\b/i, /\btrail\b/i],
  skiing: [/\bski(ing)?\b/i, /\bsnowboard(ing)?\b/i, /\baltitude\b/i],
  cycling: [/\bcycl(e|ing)\b/i, /\bbik(e|ing)\b/i],
  surfing: [/\bsurf(ing)?\b/i, /\bwave\b/i],
  sailing: [/\bsail(ing)?\b/i, /\byacht(ing)?\b/i, /\bmarine\b/i],
};

function toCategoryKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function canonicalCategoryKey(value: unknown): string | null {
  const key = toCategoryKey(value);
  if (!key) return null;
  const mapped = CATEGORY_ALIAS[key] ?? key;
  if (/(culture|cultural|heritage)/.test(key)) return 'cultural';
  if (/(museum|landmark|historic|monument|plaza|fountain)/.test(key)) return 'cultural';
  if (/(temple|church|worship|mosque|synagogue)/.test(key)) return 'temples';
  if (/(restaurant|cafe|bar|bakery|food|meal)/.test(key)) return 'food';
  if (/(park|garden|nature|zoo|camp)/.test(key)) return 'nature';
  if (/(shop|store|market|mall)/.test(key)) return 'shopping';
  if (/(spa|wellness|gym|beauty)/.test(key)) return 'spa';
  if (/(tour|point_of_interest|visitor|travel_agency)/.test(key)) return 'tours';
  return mapped;
}

function resolveBlockCategory(block: DayBlock): string | null {
  if (block.is_buffer) return null;
  const activityType = toCategoryKey(block.activity_type);
  if (activityType && NON_ACTIVITY_TYPES.has(activityType)) return null;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : undefined;

  return (
    canonicalCategoryKey(block.map_type) ??
    canonicalCategoryKey(block.specialist_type) ??
    canonicalCategoryKey(bookedTile?.map_type) ??
    canonicalCategoryKey(meta?.map_type) ??
    canonicalCategoryKey((bookedTile as Record<string, unknown> | undefined)?.browse_category) ??
    canonicalCategoryKey(bookedTile?.category) ??
    canonicalCategoryKey(meta?.category)
  );
}

function inferConstraintCategories(block: DayBlock): string[] {
  const categories = new Set<string>();
  const specialist = canonicalCategoryKey(block.specialist_type);
  if (specialist && specialist in TIER1_CONSTRAINT_HINTS) {
    categories.add(specialist);
  }

  const textParts: string[] = [];
  if (typeof block.buffer_reason === 'string') textParts.push(block.buffer_reason);
  if (Array.isArray(block.constraints)) textParts.push(...block.constraints.filter((c): c is string => typeof c === 'string'));
  if (Array.isArray(block.active_constraints)) {
    block.active_constraints.forEach((c) => {
      if (typeof c.id === 'string') textParts.push(c.id);
      if (typeof c.title === 'string') textParts.push(c.title);
      if (typeof c.description === 'string') textParts.push(c.description);
    });
  }
  const text = textParts.join(' ');
  if (!text) return Array.from(categories);

  Object.entries(TIER1_CONSTRAINT_HINTS).forEach(([category, patterns]) => {
    if (patterns.some((p) => p.test(text))) {
      categories.add(category);
    }
  });
  return Array.from(categories);
}

function inferCategoriesFromDayCards(dayCards: DayCard[] | undefined): string[] {
  if (!dayCards || dayCards.length === 0) return [];
  const inferred = new Set<string>();
  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      const category = resolveBlockCategory(block);
      if (category) inferred.add(category);
      inferConstraintCategories(block).forEach((c) => inferred.add(c));
    });
  });
  return Array.from(inferred);
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
        // Mobile: h-10 (40px) for better touch, Desktop: h-8 (32px) compact for narrow panels
        'inline-flex items-center gap-1.5 rounded-lg flex-shrink-0 cursor-pointer',
        isMobile ? 'h-10 px-4' : 'h-8 px-3',
        'transition-all duration-200 ease-out active:scale-[0.98]',
        // Hover: Scale 1.02 + snap-to-black/white (DS Tactile Rule)
        'hover:scale-[1.02] hover:border-zinc-900',
        // Dark hover: emerald accent per DS "Bioluminescent" aesthetic
        'dark:hover:border-emerald-500/50',

        // --- STATE: SET (has user value) --- DS Tactile Rule: border-2, solid fill
        isSet && [
          'bg-zinc-50',
          'border-2 border-zinc-900/30',
          'text-zinc-900 font-semibold',
          'dark:bg-white/10 dark:text-white dark:border-emerald-500/30',
          'dark:hover:bg-white/15',
        ],

        // --- STATE: OPTIONAL (unset) --- DS Tactile Rule: border-2 dashed
        !isSet && isOptional && [
          'bg-white',
          'border-2 border-dashed border-zinc-200',
          'text-zinc-400',
          'dark:bg-white/5 dark:border-white/15 dark:text-zinc-500',
          'dark:hover:border-white/30 dark:hover:text-zinc-300',
        ],

        // --- STATE: UNSET REQUIRED --- DS Tactile Rule: border-2 solid
        !isSet && !isOptional && [
          'bg-white',
          'border-2 border-zinc-200',
          'text-zinc-400',
          'dark:bg-white/5 dark:text-zinc-500 dark:border-white/15',
          'dark:hover:border-white/30 dark:hover:text-white',
        ],

        // Focus ring - zinc light / emerald dark per DS
        'focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/20',

        // --- STATE: DISABLED (BOOKING mode) ---
        disabled && [
          'opacity-50 cursor-not-allowed pointer-events-none',
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
          disabled && 'opacity-50'
        )}
      />
      <span className="text-xs font-semibold uppercase tracking-wide whitespace-nowrap">
        {value || label}
        {!value && isOptional && (
          <span className={`${DS.textSize.micro} opacity-50 ml-1 normal-case tracking-normal`}>(opt)</span>
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
        // Mobile: h-11 (44px) for Apple's minimum, Desktop: h-9 (36px) compact for narrow panels
        'inline-flex items-center gap-1.5 rounded-full flex-shrink-0',
        isMobile ? 'h-11 px-5' : 'h-9 px-4',
        'transition-all duration-200 ease-out active:scale-[0.95]',

        // --- STATE: OFF (inactive) --- DS Tactile Rule: border-2, snap-to-black hover
        isOff && [
          'bg-white',
          'border-2 border-zinc-200',
          'text-zinc-400',
          'hover:border-zinc-900 hover:text-zinc-600',
          'dark:bg-white/5 dark:border-white/15 dark:text-zinc-500',
          'dark:hover:border-white/30 dark:hover:text-zinc-300',
        ],

        // --- STATE: ON (active) --- DS Tactile Rule: solid fill, maximum contrast
        isOn && [
          'bg-zinc-900 text-white',
          'border-2 border-transparent',
          'font-medium',
          'hover:bg-zinc-800',
          'dark:bg-white dark:text-black dark:border-transparent',
          'dark:hover:bg-zinc-100',
        ],

        // Focus ring - zinc light / emerald dark per DS
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-900/20 dark:focus-visible:ring-emerald-500/30',

        // --- STATE: DISABLED (BOOKING mode) ---
        disabled && 'opacity-50 cursor-not-allowed pointer-events-none'
      )}
    >
      {/* Checkmark for active state (replaces icon position) */}
      {/* DS: zinc-900 light / emerald dark for accent elements */}
      {isOn ? (
        <Check className="h-4 w-4 flex-shrink-0 text-white dark:text-emerald-500" strokeWidth={2.5} />
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
  const selectedActivityCount = getActivitySelectedCount(activitySettings, inferredActivityCategories);

  // Check if travelers has been modified from default
  const isTravelersDefault = travelers === '1 adult';

  return (
    <div className="flex flex-col gap-2 w-full">
      {/* MOBILE ROW 1: TRIP PARAMS (Where & When) */}
      {/* DESKTOP ROW 1: All 5 core chips on one line (no-wrap, scrollable if needed) */}
      {isMobile ? (
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar -mx-4 px-4 py-1">
          <CoreChip icon={MapPin} label="Destination" value={destination} onClick={destinationLocked ? undefined : onOpenDestination} isMobile disabled={isBookingMode} />
          <CoreChip icon={Plane} label="Origin" value={origin} onClick={onOpenOrigin} isMobile disabled={isBookingMode} />
          <CoreChip icon={Calendar} label="Dates" value={dateRange} onClick={onOpenDates} isMobile disabled={isBookingMode} />
          <CoreChip icon={Users} label="Travelers" value={travelers} onClick={onOpenTravelers} isDefault={isTravelersDefault} isMobile disabled={isBookingMode} />
          <CoreChip icon={DollarSign} label="Budget" value={budget} onClick={onOpenBudget} isOptional isMobile disabled={isBookingMode} />
        </div>
      ) : (
        /* Desktop: single row, centered. Parent ChatMessageList uses overflow-x-clip + -mx-4 px-4
           so the clip boundary is the full panel width — chips won't get cut. */
        <div className="flex items-center gap-1.5 flex-nowrap justify-center">
          <CoreChip icon={MapPin} label="Destination" value={destination} onClick={destinationLocked ? undefined : onOpenDestination} disabled={isBookingMode} />
          <CoreChip icon={Plane} label="Origin" value={origin} onClick={onOpenOrigin} disabled={isBookingMode} />
          <CoreChip icon={Calendar} label="Dates" value={dateRange} onClick={onOpenDates} disabled={isBookingMode} />
          <CoreChip icon={Users} label="Travelers" value={travelers} onClick={onOpenTravelers} isDefault={isTravelersDefault} disabled={isBookingMode} />
          <CoreChip icon={DollarSign} label="Budget" value={budget} onClick={onOpenBudget} isOptional disabled={isBookingMode} />
        </div>
      )}

      {/* MOBILE ROW 2: TRAVELERS (separate row on mobile only) */}
      {isMobile && (
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar -mx-4 px-4 py-1">
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
          label={selectedActivityCount > 0 ? `Activities(${selectedActivityCount})` : 'Activities'}
          state={getActivitiesState()}
          summary={null}
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
