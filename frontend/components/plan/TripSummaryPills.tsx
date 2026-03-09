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
import { Fragment, type ReactNode, useCallback, useEffect, useRef, useState } from 'react';

import { canonicalCategoryKey } from '@/lib/categoryNormalization';
import { DS } from '@/lib/design-system';
import { formatBudgetForPills, formatDateRangeForPills, formatTravelersForPills } from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

import { deriveScheduledDayCounts } from './tripSummaryUtils';

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
        'inline-flex items-center gap-1.5 rounded-full',
        compact ? 'h-8' : 'h-10',
        compact ? 'px-2' : 'px-3',
        compact ? 'text-xs' : DS.textSize.badgeLabel,
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
      <div className={cn('w-1 h-1 rounded-full bg-emerald-500/50', DS.glowClass.dotGlow)} />
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
        `inline-flex items-center justify-center ${DS.textSize.micro} font-bold`,
        'bg-white text-zinc-900'
      )}
    >
      {count}
    </span>
  );
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
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [showRightFade, setShowRightFade] = useState(false);

  const updateFadeState = useCallback(() => {
    const element = scrollRef.current;
    if (!element || compact) {
      setShowRightFade(false);
      return;
    }

    const hasOverflow = element.scrollWidth - element.clientWidth > 4;
    const atEnd = element.scrollLeft + element.clientWidth >= element.scrollWidth - 4;
    setShowRightFade(hasOverflow && !atEnd);
  }, [compact]);

  useEffect(() => {
    updateFadeState();
    const element = scrollRef.current;
    if (!element || compact) return;

    const handleScroll = () => updateFadeState();
    element.addEventListener('scroll', handleScroll, { passive: true });

    const resizeObserver =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => updateFadeState());
    resizeObserver?.observe(element);
    if (element.firstElementChild instanceof HTMLElement) {
      resizeObserver?.observe(element.firstElementChild);
    }

    window.addEventListener('resize', updateFadeState);
    return () => {
      element.removeEventListener('scroll', handleScroll);
      resizeObserver?.disconnect();
      window.removeEventListener('resize', updateFadeState);
    };
  }, [compact, updateFadeState]);

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
    <div className="relative">
      <div
        ref={scrollRef}
        className={cn(
          compact
            ? ''
            : 'overflow-x-auto no-scrollbar flex-nowrap -mx-4 px-4 py-2 lg:overflow-x-visible lg:flex-wrap',
        )}
      >
        <div
          className={cn(
            'inline-flex items-center',
            compact ? 'h-9' : 'h-10',
            'rounded-xl',
            'px-1.5',
            'bg-white/[0.05]',
            'backdrop-blur-xl',
            'border border-white/[0.08]',
            DS.glowClass.commandBar,
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
      {!compact && showRightFade && (
        <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-white dark:from-zinc-950 to-transparent lg:hidden" />
      )}
    </div>
  );
}

export default TripSummaryPills;
