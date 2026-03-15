'use client';

import type { LucideIcon } from 'lucide-react';
import { Activity, Calendar, DollarSign, MapPin, Plane, Users } from 'lucide-react';

import { canonicalCategoryKey } from '@/lib/categoryNormalization';
import { formatBudgetForPills, formatDateRangeForPills, formatTravelersForPills } from '@/lib/format-utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

import { deriveScheduledDayCounts } from './tripSummaryUtils';

export interface TripSummaryPillsProps {
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

export interface CoreSegmentItem {
  key: string;
  icon: LucideIcon;
  label: string;
  isSet?: boolean;
  badge?: number;
  onClick?: () => void;
  disabled?: boolean;
}

export function getTripSummaryFields(tripInputs: DocumentTripInputs, dayCards?: DayCard[]) {
  const destination = tripInputs.destination || null;
  const origin = tripInputs.origin?.trim() || null;
  const dateRange = formatDateRangeForPills(tripInputs.start_date, tripInputs.end_date);
  const travelers = formatTravelersForPills(tripInputs.adults, tripInputs.children);
  const budget = formatBudgetForPills(tripInputs.budget, tripInputs.currency);
  const normalizedSelected = (tripInputs.activity_settings?.categories ?? [])
    .map((category) => canonicalCategoryKey(category))
    .filter((category): category is string => !!category);
  const scheduledCounts = deriveScheduledDayCounts(dayCards, normalizedSelected);
  const hasItinerary = (dayCards?.length ?? 0) > 0;
  const dedupedSelected = normalizedSelected.filter(
    (category, index, values) => values.indexOf(category) === index
  );
  const selectedActivityCount = hasItinerary
    ? (dedupedSelected.length > 0 ? dedupedSelected : Array.from(scheduledCounts.keys())).length
    : dedupedSelected.length;

  return {
    destination,
    origin,
    dateRange,
    travelers,
    budget,
    selectedActivityCount,
    hasActivitiesSet: selectedActivityCount > 0,
  };
}

export function buildCoreSegments({
  destination,
  origin,
  dateRange,
  travelers,
  budget,
  hasActivitiesSet,
  selectedActivityCount,
  onOpenSheet,
  disabled,
  readOnlyExceptDestination,
}: {
  destination: string | null;
  origin: string | null;
  dateRange: string | null;
  travelers: string;
  budget: string | null;
  hasActivitiesSet: boolean;
  selectedActivityCount: number;
  onOpenSheet: (sheet: SheetType) => void;
  disabled: boolean;
  readOnlyExceptDestination: boolean;
}): CoreSegmentItem[] {
  return [
    {
      key: 'destination',
      icon: MapPin,
      label: destination || 'Where to?',
      isSet: !!destination,
      onClick: destination ? undefined : () => onOpenSheet('destination'),
      disabled,
    },
    ...(origin
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
    ...(budget
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
}
