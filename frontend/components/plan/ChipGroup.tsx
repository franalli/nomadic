'use client';

/**
 * ChipGroup
 *
 * Presentational chip components and state-computation helpers
 * for the UnifiedChipRow "cockpit" layout.
 *
 * Exports:
 * - SetupCoreChip  — Row A compact pill (destination, origin, dates, etc.)
 * - ModuleChip     — Row B toggle pill (flights, stays, activities)
 * - Chip-state helpers (isFlightCustom, getFlightChipSummary, etc.)
 * - Category-inference helpers (inferCategoriesFromDayCards, etc.)
 */

import {
  Check,
  type LucideIcon,
} from 'lucide-react';
import { memo } from 'react';

import {
  canonicalCategoryKey,
  TIER1_CONSTRAINT_HINTS,
  toCategoryKey,
} from '@/lib/categoryNormalization';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import type {
  ActivitySettings,
  FlightSettings,
  HotelSettings,
} from '@/types/document';
import type { DayBlock, DayCard } from '@/types/plan-envelope';

// ─────────────────────────────────────────────────────────────────────────────
// Chip Defaults (for detecting "custom" state)
// ─────────────────────────────────────────────────────────────────────────────

export const isFlightCustom = (settings?: FlightSettings): boolean => {
  if (!settings) return false;
  return (
    settings.cabin_class !== 'economy' ||
    settings.direct_only === true ||
    settings.round_trip === false
  );
};

export const isHotelCustom = (settings?: HotelSettings): boolean => {
  if (!settings) return false;
  return (
    (settings.min_stars !== undefined && settings.min_stars > 0) ||
    (settings.amenities !== undefined && settings.amenities.length > 0)
  );
};

export const isActivityCustom = (
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

export function getFlightChipSummary(settings?: FlightSettings): string | null {
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

export function getHotelChipSummary(settings?: HotelSettings): string | null {
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

export function getActivitySelectedCount(
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

// ─────────────────────────────────────────────────────────────────────────────
// Category Inference from Day Cards
// ─────────────────────────────────────────────────────────────────────────────

const NON_ACTIVITY_TYPES = new Set([
  'arrival', 'departure', 'check-in', 'check-out', 'check_in', 'check_out',
  'free_day', 'rest_day', 'buffer', 'decompression_buffer',
]);

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

export function inferCategoriesFromDayCards(dayCards: DayCard[] | undefined): string[] {
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
// SetupCoreChip (Row A) — compact trip-param pills
// ─────────────────────────────────────────────────────────────────────────────

export interface SetupCoreChipProps {
  icon: LucideIcon;
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

export const SetupCoreChip = memo(function SetupCoreChip({
  icon: Icon,
  label,
  value,
  onClick,
  isOptional,
  isDefault = false,
  isMobile = false,
  disabled = false,
}: SetupCoreChipProps) {
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
// ModuleChip (Row B) — 3-state toggle: off -> on-default -> on-custom
// ─────────────────────────────────────────────────────────────────────────────

export type ModuleState = 'off' | 'on-default' | 'on-custom';

export interface ModuleChipProps {
  icon: LucideIcon;
  label: string;
  state: ModuleState;
  summary?: string | null;
  onClick?: () => void;
  /** Mobile mode - larger touch targets */
  isMobile?: boolean;
  /** Disabled state (e.g., in BOOKING mode) */
  disabled?: boolean;
}

export const ModuleChip = memo(function ModuleChip({
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
