/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * TripSummaryPills
 *
 * Unified command bar for trip inputs + module openers.
 * Replaces standalone pills with one elevated command surface.
 */

'use client';

import type { LucideIcon } from 'lucide-react';
import { Activity, Building2, Calendar, Compass, DollarSign, Lightbulb, MapPin, Plane, Users } from 'lucide-react';
import { Fragment, type ReactNode } from 'react';

import { canonicalCategoryKey, TIER1_CONSTRAINT_HINTS, toCategoryKey } from '@/lib/categoryNormalization';
import { formatBudgetForPills, formatDateRangeForPills, formatTravelersForPills } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DayBlock, DayCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface TripSummaryPillsProps {
  tripInputs: DocumentTripInputs;
  dayCards?: DayCard[];
  onOpenSheet: (sheet: SheetType) => void;
  disabled?: boolean;
  variant?: 'default' | 'onImage';
  readOnlyExceptDestination?: boolean;
  compact?: boolean;
  flightCount?: number;
  stayCount?: number;
  travelAdviceCount?: number;
  showTravelAdvice?: boolean;
  isTravelAdvicePending?: boolean;
  flightsActive?: boolean;
  staysActive?: boolean;
  travelAdviceActive?: boolean;
  onToggleFlights?: () => void;
  onToggleStays?: () => void;
  onToggleTravelAdvice?: () => void;
}

interface SegmentProps {
  icon: LucideIcon;
  label: string;
  badge?: number;
  isSet?: boolean;
  muted?: boolean;
  active?: boolean;
  disabled?: boolean;
  compact?: boolean;
  onClick?: () => void;
  id?: string;
  ariaControls?: string;
  ariaExpanded?: boolean;
  trailing?: ReactNode;
}

interface CoreSegmentItem {
  key: string;
  icon: LucideIcon;
  label: string;
  isSet?: boolean;
  badge?: number;
  onClick?: () => void;
  disabled?: boolean;
}

const NON_ACTIVITY_TYPES = new Set([
  'arrival',
  'departure',
  'check-in',
  'check-out',
  'check_in',
  'check_out',
  'free_day',
  'rest_day',
  'buffer',
  'decompression_buffer',
]);

function Segment({
  icon: Icon,
  label,
  badge,
  isSet = false,
  muted = false,
  active = false,
  disabled = false,
  compact = false,
  onClick,
  id,
  ariaControls,
  ariaExpanded,
  trailing,
}: SegmentProps) {
  const interactive = Boolean(onClick) && !disabled;

  return (
    <button
      id={id}
      type="button"
      onClick={onClick}
      disabled={!interactive}
      aria-controls={ariaControls}
      aria-expanded={ariaExpanded}
      className={cn(
        'inline-flex items-center gap-1.5 h-8 rounded-full',
        compact ? 'px-2' : 'px-3',
        compact ? 'text-xs' : 'text-[13px]',
        'whitespace-nowrap transition-all duration-150',
        'hover:bg-white/[0.08]',
        interactive ? 'cursor-pointer' : 'cursor-default opacity-70',
        muted
          ? cn(
              active ? 'text-zinc-200' : 'text-zinc-400',
              'font-medium',
              'hover:text-zinc-200'
            )
          : isSet
            ? 'font-semibold text-zinc-100'
            : 'text-zinc-500'
      )}
    >
      <Icon
        className={cn(
          'h-4 w-4 shrink-0',
          muted
            ? cn(active ? 'text-zinc-300' : 'text-zinc-500')
            : isSet
              ? 'text-emerald-400/80'
              : 'text-zinc-600'
        )}
      />
      <span>{label}</span>
      {trailing}
      {badge && badge > 0 ? <CountBadge count={badge} /> : null}
    </button>
  );
}

function SegDot() {
  return (
    <div className="flex items-center px-1.5">
      <div className="w-1 h-1 rounded-full bg-emerald-500/50 shadow-[0_0_6px_rgba(16,185,129,0.3)]" />
    </div>
  );
}

function GroupDivider() {
  return (
    <div className="flex items-center px-2">
      <div className="w-px h-5 bg-white/[0.15]" />
    </div>
  );
}

function CountBadge({ count }: { count: number }) {
  return (
    <span
      className={cn(
        'ml-0.5 min-w-[18px] h-[18px] rounded-full px-1',
        'inline-flex items-center justify-center text-[10px] font-bold',
        'bg-white text-zinc-900'
      )}
    >
      {count}
    </span>
  );
}

function resolveBlockCategory(block: DayBlock): string | null {
  if (block.is_buffer) return null;
  const activityType = toCategoryKey(block.activity_type);
  if (activityType && NON_ACTIVITY_TYPES.has(activityType)) return null;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? (bookedTile.meta as Record<string, unknown>)
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
  if (Array.isArray(block.constraints)) {
    textParts.push(...block.constraints.filter((c): c is string => typeof c === 'string'));
  }
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
    if (patterns.some((pattern) => pattern.test(text))) {
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
    selected.forEach((cat) => categoryToDays.set(cat, new Set<number>()));

    dayCards.forEach((card) => {
      card.blocks?.forEach((block) => {
        const inferredConstraints = new Set(inferConstraintCategories(block));
        selected.forEach((selectedCategory) => {
          if (
            inferredConstraints.has(selectedCategory) ||
            blockMatchesCategory(block, selectedCategory)
          ) {
            categoryToDays.get(selectedCategory)?.add(card.day_number);
          }
        });
      });
    });
  } else {
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
  variant: _variant = 'default',
  readOnlyExceptDestination = false,
  compact = false,
  flightCount = 0,
  stayCount = 0,
  travelAdviceCount = 0,
  showTravelAdvice = false,
  isTravelAdvicePending = false,
  flightsActive = false,
  staysActive = false,
  travelAdviceActive = false,
  onToggleFlights,
  onToggleStays,
  onToggleTravelAdvice,
}: TripSummaryPillsProps) {
  const destination = tripInputs.destination || null;
  const origin = tripInputs.origin?.trim() || null;
  const dateRange = formatDateRangeForPills(tripInputs.start_date, tripInputs.end_date);
  const travelers = formatTravelersForPills(tripInputs.adults, tripInputs.children);
  const budget = formatBudgetForPills(tripInputs.budget, tripInputs.currency);

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
  const hasActivitiesSet = selectedActivityCount > 0;

  const showFlights = flightCount > 0 && !!onToggleFlights;
  const showStays = stayCount > 0 && !!onToggleStays;
  const showAdvice = (showTravelAdvice || travelAdviceCount > 0 || isTravelAdvicePending) && !!onToggleTravelAdvice;
  const showModuleGroup = showFlights || showStays || showAdvice;
  const showOrigin = !!origin;
  const showBudget = !!budget;

  const coreSegments: CoreSegmentItem[] = [
    {
      key: 'destination',
      icon: MapPin,
      label: destination || 'Where to?',
      isSet: !!destination,
      onClick: destination ? undefined : () => onOpenSheet('destination'),
      disabled,
    },
    ...(showOrigin
      ? [{
          key: 'origin',
          icon: Plane,
          label: origin,
          isSet: true,
          onClick: readOnlyExceptDestination ? undefined : () => onOpenSheet('origin'),
          disabled: disabled || readOnlyExceptDestination,
        }]
      : []),
    {
      key: 'dates',
      icon: Calendar,
      label: dateRange || 'Dates',
      isSet: !!dateRange,
      onClick: readOnlyExceptDestination ? undefined : () => onOpenSheet('dates'),
      disabled: disabled || readOnlyExceptDestination,
    },
    {
      key: 'travelers',
      icon: Users,
      label: travelers,
      isSet: true,
      onClick: readOnlyExceptDestination ? undefined : () => onOpenSheet('travelers'),
      disabled: disabled || readOnlyExceptDestination,
    },
    ...(showBudget
      ? [{
          key: 'budget',
          icon: DollarSign,
          label: budget,
          isSet: true,
          onClick: readOnlyExceptDestination ? undefined : () => onOpenSheet('budget'),
          disabled: disabled || readOnlyExceptDestination,
        }]
      : []),
    {
      key: 'activities',
      icon: Activity,
      label: 'Activities',
      badge: hasActivitiesSet ? selectedActivityCount : undefined,
      isSet: hasActivitiesSet,
      onClick: readOnlyExceptDestination ? undefined : () => onOpenSheet('activities'),
      disabled: disabled || readOnlyExceptDestination,
    },
  ];

  return (
    <div className={cn(
      compact
        ? ''
        : 'overflow-x-auto no-scrollbar flex-nowrap -mx-4 px-4 py-2 lg:overflow-x-visible lg:flex-wrap',
    )}>
      <div
        className={cn(
          'inline-flex items-center',
          compact ? 'h-9' : 'h-10',
          'rounded-xl',
          'px-1.5',
          'bg-white/[0.05]',
          'backdrop-blur-xl',
          'border border-white/[0.08]',
          'shadow-[0_2px_20px_rgba(0,0,0,0.4),0_4px_24px_rgba(16,185,129,0.06),inset_0_1px_0_rgba(255,255,255,0.06)]',
          'overflow-visible',
        )}
      >
        {coreSegments.map((segment, idx) => (
          <Fragment key={segment.key}>
            <Segment
              icon={segment.icon}
              label={segment.label}
              badge={segment.badge}
              isSet={segment.isSet}
              onClick={segment.onClick}
              disabled={segment.disabled}
              compact={compact}
            />
            {idx < coreSegments.length - 1 && <SegDot />}
          </Fragment>
        ))}

        {showModuleGroup ? (
          <>
            <GroupDivider />

            {showFlights ? (
              <>
                <Segment
                  icon={Plane}
                  label="Flights"
                  badge={flightCount}
                  muted
                  active={flightsActive}
                  onClick={onToggleFlights}
                  disabled={disabled}
                  compact={compact}
                />
                {(showStays || showAdvice) && <SegDot />}
              </>
            ) : null}

            {showStays ? (
              <>
                <Segment
                  icon={Building2}
                  label="Stays"
                  badge={stayCount}
                  muted
                  active={staysActive}
                  onClick={onToggleStays}
                  disabled={disabled}
                  compact={compact}
                />
                {showAdvice && <SegDot />}
              </>
            ) : null}

            {showAdvice ? (
              <Segment
                id="destination-intel-trigger"
                icon={Lightbulb}
                label="Advice"
                badge={travelAdviceCount > 0 ? travelAdviceCount : undefined}
                muted
                active={travelAdviceActive}
                onClick={onToggleTravelAdvice}
                disabled={disabled}
                compact={compact}
                ariaControls="destination-intel-panel"
                ariaExpanded={travelAdviceActive}
                trailing={
                  isTravelAdvicePending ? (
                    <Compass
                      className="h-4 w-4 shrink-0 text-emerald-500 compass-spin"
                      aria-label="Travel advice is loading"
                    />
                  ) : undefined
                }
              />
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

export default TripSummaryPills;
