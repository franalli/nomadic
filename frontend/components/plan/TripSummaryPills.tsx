/* eslint no-unused-vars: ["error", { "args": "none" }] */
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

import { Activity, Calendar, DollarSign, MapPin, Plane, Users } from 'lucide-react';

import { CoreChip } from '@/components/plan/CoreChip';
import {
  formatBudgetForPills,
  formatDateRangeForPills,
  formatTravelersForPills,
} from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DayBlock, DayCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface TripSummaryPillsProps {
  tripInputs: DocumentTripInputs;
  dayCards?: DayCard[];
  onOpenSheet: (sheet: SheetType) => void;
  disabled?: boolean; // Disable all pills during streaming/generation
  /** Use 'onImage' when pills are on hero/photo background */
  variant?: 'default' | 'onImage';
  /** When true, make all pills except destination read-only (demo-safe for itinerary state) */
  readOnlyExceptDestination?: boolean;
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

function blockTextForMatching(block: DayBlock): string {
  return `${String(block.activity_type ?? '')} ${String(block.summary ?? '')}`.toLowerCase();
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function blockMatchesCategory(block: DayBlock, category: string): boolean {
  const resolved = resolveBlockCategory(block);
  if (resolved === category) return true;

  const haystack = blockTextForMatching(block);
  const token = category.replace(/_/g, ' ').trim().toLowerCase();
  if (!token) return false;
  const re = new RegExp(`\\b${escapeRegex(token)}\\b`, 'i');
  return re.test(haystack);
}

function deriveScheduledDayCounts(
  dayCards: DayCard[] | undefined,
  selectedCategories: string[] = []
): Map<string, number> {
  const categoryToDays = new Map<string, Set<number>>();
  if (!dayCards || dayCards.length === 0) return new Map();
  const selected = Array.from(new Set(selectedCategories));

  if (selected.length > 0) {
    // When user selected categories, those categories are authoritative for label/count display.
    selected.forEach((cat) => categoryToDays.set(cat, new Set<number>()));

    dayCards.forEach((card) => {
      card.blocks?.forEach((block) => {
        const inferredConstraints = new Set(inferConstraintCategories(block));
        selected.forEach((selectedCategory) => {
          if (inferredConstraints.has(selectedCategory) || blockMatchesCategory(block, selectedCategory)) {
            categoryToDays.get(selectedCategory)?.add(card.day_number);
          }
        });
      });
    });
  } else {
    // No user-selected categories: infer directly from itinerary metadata/constraints.
    dayCards.forEach((card) => {
      card.blocks?.forEach((block) => {
        const category = resolveBlockCategory(block);
        if (category) {
          const existing = categoryToDays.get(category) ?? new Set<number>();
          existing.add(card.day_number);
          categoryToDays.set(category, existing);
        }

        inferConstraintCategories(block).forEach((constraintCategory) => {
          const existing = categoryToDays.get(constraintCategory) ?? new Set<number>();
          existing.add(card.day_number);
          categoryToDays.set(constraintCategory, existing);
        });
      });
    });
  }

  const counts = new Map<string, number>();
  categoryToDays.forEach((days, category) => counts.set(category, days.size));
  return counts;
}

export function TripSummaryPills({
  tripInputs,
  dayCards,
  onOpenSheet,
  disabled = false,
  variant = 'default',
  readOnlyExceptDestination = false,
}: TripSummaryPillsProps) {
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

  // Activity pill label — always derive from actual itinerary when day_cards exist.
  const activityCategories = tripInputs.activity_settings?.categories ?? [];
  const normalizedSelected = activityCategories
    .map((c) => canonicalCategoryKey(c))
    .filter((c): c is string => !!c);
  const scheduledCounts = deriveScheduledDayCounts(dayCards, normalizedSelected);
  const hasItinerary = (dayCards?.length ?? 0) > 0;

  const dedupedSelected = normalizedSelected.filter((c, idx, arr) => arr.indexOf(c) === idx);
  let selectedActivityCount = dedupedSelected.length;
  if (hasItinerary) {
    const scheduledKeys = Array.from(scheduledCounts.keys());
    const effectiveSelected = dedupedSelected.length > 0 ? dedupedSelected : scheduledKeys;
    selectedActivityCount = effectiveSelected.length;
  }
  const activityLabel = selectedActivityCount > 0 ? `Activities(${selectedActivityCount})` : null;

  // Origin visibility: only show when origin is already set (ghost pill confuses destination relationship)
  const showOrigin = !!origin;

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 flex-wrap',
        // Prevent pills from shrinking
        '[&>*]:shrink-0'
      )}
    >
      <CoreChip
        icon={MapPin}
        label="Destination"
        value={destination}
        placeholder="Add destination"
        tone={destination ? 'default' : 'missing'}
        onClick={destination ? undefined : () => onOpenSheet('destination')}
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
          onClick={readOnlyExceptDestination ? undefined : () => onOpenSheet('origin')}
          disabled={disabled || readOnlyExceptDestination}
          variant={variant}
        />
      )}

      <CoreChip
        icon={Calendar}
        label="Dates"
        value={dateRange}
        placeholder="Add dates"
        tone={dateRange ? 'default' : 'missing'}
        onClick={readOnlyExceptDestination ? undefined : () => onOpenSheet('dates')}
        disabled={disabled || readOnlyExceptDestination}
        variant={variant}
      />

      <CoreChip
        icon={Users}
        label="Travelers"
        value={travelers}
        placeholder="1 adult"
        tone="default"
        onClick={readOnlyExceptDestination ? undefined : () => onOpenSheet('travelers')}
        disabled={disabled || readOnlyExceptDestination}
        variant={variant}
      />

      <CoreChip
        icon={Activity}
        label="Activities"
        value={activityLabel}
        placeholder="Activities"
        tone={activityLabel ? 'default' : 'optional'}
        onClick={readOnlyExceptDestination ? undefined : () => onOpenSheet('activities')}
        disabled={disabled || readOnlyExceptDestination}
        variant={variant}
      />

      <CoreChip
        icon={DollarSign}
        label="Budget"
        value={budget}
        placeholder="Budget (optional)"
        tone="optional"
        onClick={readOnlyExceptDestination ? undefined : () => onOpenSheet('budget')}
        disabled={disabled || readOnlyExceptDestination}
        variant={variant}
        className="italic"
      />

    </div>
  );
}

export default TripSummaryPills;
