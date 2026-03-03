'use client';

import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  Building2,
  Calendar,
  DollarSign,
  Lightbulb,
  MapPin,
  Plane,
  Users,
} from 'lucide-react';
import { useMemo } from 'react';

import { DS } from '@/lib/design-system';
import {
  formatBudgetForPills,
  formatDateRangeForPills,
  formatTravelersForPills,
} from '@/lib/format-utils';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { SheetType } from '@/types/sheets';

interface TripChromeBarProps {
  tripInputs?: DocumentTripInputs;
  onOpenSheet: (sheet: SheetType) => void;
  disabled?: boolean;
  stayCount?: number;
  flightCount?: number;
  travelAdviceCount?: number;
  staysExpanded?: boolean;
  flightsExpanded?: boolean;
  travelAdviceExpanded?: boolean;
  onToggleStays?: () => void;
  onToggleFlights?: () => void;
  onToggleTravelAdvice?: () => void;
}

interface Segment {
  key: string;
  icon: LucideIcon;
  value: string;
  count?: number;
  onClick?: () => void;
  configured?: boolean;
  active?: boolean;
}

export function TripChromeBar({
  tripInputs,
  onOpenSheet,
  disabled = false,
  stayCount = 0,
  flightCount = 0,
  travelAdviceCount = 0,
  staysExpanded = false,
  flightsExpanded = false,
  travelAdviceExpanded = false,
  onToggleStays,
  onToggleFlights,
  onToggleTravelAdvice,
}: TripChromeBarProps) {
  const destination = tripInputs?.destination?.trim() || null;
  const origin = tripInputs?.origin?.trim() || null;
  const dateRange = formatDateRangeForPills(tripInputs?.start_date, tripInputs?.end_date);
  const travelers = formatTravelersForPills(tripInputs?.adults, tripInputs?.children);
  const budget = formatBudgetForPills(tripInputs?.budget, tripInputs?.currency);
  const activityCount = useMemo(() => {
    const categories = tripInputs?.activity_settings?.categories ?? [];
    return new Set(categories).size;
  }, [tripInputs?.activity_settings?.categories]);

  const segments = useMemo(() => {
    const base: Segment[] = [
      {
        key: 'destination',
        icon: MapPin,
        value: destination ?? 'Add destination',
        configured: !!destination,
        onClick: destination ? undefined : () => onOpenSheet('destination'),
      },
      {
        key: 'dates',
        icon: Calendar,
        value: dateRange ?? 'Add dates',
        configured: !!dateRange,
        onClick: () => onOpenSheet('dates'),
      },
      {
        key: 'travelers',
        icon: Users,
        value: travelers,
        configured: true,
        onClick: () => onOpenSheet('travelers'),
      },
      {
        key: 'activities',
        icon: Activity,
        value: activityCount > 0 ? 'Activities' : 'Set activities',
        count: activityCount > 0 ? activityCount : undefined,
        configured: activityCount > 0,
        onClick: () => onOpenSheet('activities'),
      },
    ];

    if (origin) {
      base.splice(1, 0, {
        key: 'origin',
        icon: Plane,
        value: origin,
        configured: true,
        onClick: () => onOpenSheet('origin'),
      });
    }

    if (budget) {
      base.push({
        key: 'budget',
        icon: DollarSign,
        value: budget,
        configured: true,
        onClick: () => onOpenSheet('budget'),
      });
    }

    if (flightCount > 0 && onToggleFlights) {
      base.push({
        key: 'flights',
        icon: Plane,
        value: 'Flights',
        count: flightCount,
        onClick: onToggleFlights,
        configured: true,
        active: flightsExpanded,
      });
    }

    if (stayCount > 0 && onToggleStays) {
      base.push({
        key: 'stays',
        icon: Building2,
        value: 'Stays',
        count: stayCount,
        onClick: onToggleStays,
        configured: true,
        active: staysExpanded,
      });
    }

    if (travelAdviceCount > 0 && onToggleTravelAdvice) {
      base.push({
        key: 'travel-advice',
        icon: Lightbulb,
        value: 'Travel Advice',
        count: travelAdviceCount,
        onClick: onToggleTravelAdvice,
        configured: true,
        active: travelAdviceExpanded,
      });
    }

    return base;
  }, [
    activityCount,
    budget,
    dateRange,
    destination,
    flightCount,
    flightsExpanded,
    onOpenSheet,
    onToggleFlights,
    onToggleStays,
    onToggleTravelAdvice,
    origin,
    stayCount,
    staysExpanded,
    travelers,
    travelAdviceCount,
    travelAdviceExpanded,
  ]);

  return (
    <div className="min-w-0 overflow-x-auto no-scrollbar">
      <div className={cn(DS.segments.container, 'min-w-max bg-white/75 dark:bg-white/[0.03]')}>
        {segments.map((segment) => {
          const Icon = segment.icon;
          const isInteractive = Boolean(segment.onClick) && !disabled;
          return (
            <button
              key={segment.key}
              type="button"
              onClick={segment.onClick}
              disabled={!isInteractive}
              title={segment.value}
              aria-label={`${segment.value}${segment.count ? ` (${segment.count})` : ''}`}
              className={cn(
                DS.segments.segment,
                'relative h-9 min-w-[122px] flex-row items-center justify-center gap-1.5 px-2.5 py-0',
                segment.active ? DS.segments.segmentActive : DS.segments.segmentInactive,
                !segment.active && segment.configured && 'text-zinc-700 dark:text-zinc-200',
                !segment.active && !segment.configured && 'text-zinc-500 dark:text-zinc-500',
                !isInteractive && 'cursor-default opacity-70'
              )}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 truncate text-xs font-medium">{segment.value}</span>
              {segment.count && segment.count > 0 && (
                <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full border border-zinc-300 px-1 text-[10px] font-semibold dark:border-white/20">
                  {segment.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default TripChromeBar;
