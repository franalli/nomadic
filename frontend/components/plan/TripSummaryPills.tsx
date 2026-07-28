/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { Building2, Compass, Lightbulb, Plane } from 'lucide-react';
import { Fragment, useRef } from 'react';

import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

import {
  buildCoreSegments,
  getTripSummaryFields,
  type TripSummaryPillsProps,
} from './TripSummaryPills.helpers';
import {
  TripSummaryGroupDivider,
  TripSummarySegment,
  TripSummarySegmentDot,
} from './TripSummaryPillsSegment';
import { useTripSummaryFade } from './useTripSummaryFade';

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
  const {
    destination,
    origin,
    dateRange,
    travelers,
    budget,
    selectedActivityCount,
    hasActivitiesSet,
  } = getTripSummaryFields(tripInputs, dayCards);
  const showFlights = flightCount > 0 && !!onToggleFlights;
  const showStays = stayCount > 0 && !!onToggleStays;
  const showAdvice =
    (showTravelAdvice || travelAdviceCount > 0 || isTravelAdvicePending) && !!onToggleTravelAdvice;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const showRightFade = useTripSummaryFade(scrollRef);
  const coreSegments = buildCoreSegments({
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
  });

  return (
    <div className={cn('relative', compact && 'min-w-0 max-w-full')}>
      <div
        ref={scrollRef}
        className={cn(
          compact
            ? // Header mode: contain + scroll within the center flex area (no
              // negative-margin bleed — the bar must never overlap neighbors).
              'no-scrollbar max-w-full flex-nowrap overflow-x-auto'
            : 'no-scrollbar -mx-4 flex-nowrap overflow-x-auto px-4 py-2 lg:flex-wrap lg:overflow-x-visible'
        )}
      >
        <div
          className={cn(
            'inline-flex items-center rounded-xl border border-white/[0.08] bg-white/[0.05] px-1.5 backdrop-blur-xl',
            compact ? 'h-9' : 'h-10',
            DS.glowClass.commandBar
          )}
        >
          {coreSegments.map((segment, index) => (
            <Fragment key={segment.key}>
              <TripSummarySegment
                icon={segment.icon}
                label={segment.label}
                badge={segment.badge}
                isSet={segment.isSet}
                onClick={segment.onClick}
                disabled={segment.disabled}
                compact={compact}
              />
              {index < coreSegments.length - 1 && <TripSummarySegmentDot />}
            </Fragment>
          ))}

          {(showFlights || showStays || showAdvice) && (
            <>
              <TripSummaryGroupDivider />
              {showFlights && (
                <>
                  <TripSummarySegment
                    icon={Plane}
                    label="Flights"
                    badge={flightCount}
                    muted
                    active={flightsActive}
                    onClick={onToggleFlights}
                    disabled={disabled}
                    toggleable
                    compact={compact}
                  />
                  {(showStays || showAdvice) && <TripSummarySegmentDot />}
                </>
              )}
              {showStays && (
                <>
                  <TripSummarySegment
                    icon={Building2}
                    label="Stays"
                    badge={stayCount}
                    muted
                    active={staysActive}
                    onClick={onToggleStays}
                    disabled={disabled}
                    toggleable
                    compact={compact}
                  />
                  {showAdvice && <TripSummarySegmentDot />}
                </>
              )}
              {showAdvice && (
                <TripSummarySegment
                  id="destination-intel-trigger"
                  icon={Lightbulb}
                  label="Advice"
                  badge={travelAdviceCount > 0 ? travelAdviceCount : undefined}
                  muted
                  active={travelAdviceActive}
                  onClick={onToggleTravelAdvice}
                  disabled={disabled}
                  toggleable
                  compact={compact}
                  ariaControls="destination-intel-panel"
                  ariaExpanded={travelAdviceActive}
                  trailing={
                    isTravelAdvicePending ? (
                      <Compass
                        className="compass-spin h-4 w-4 shrink-0 text-emerald-500"
                        aria-label="Travel advice is loading"
                      />
                    ) : undefined
                  }
                />
              )}
            </>
          )}
        </div>
      </div>
      {showRightFade && (
        <div
          className={cn(
            'pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l to-transparent',
            compact
              ? // Header sits on the theme panel surface — fade must match it.
                'from-[var(--theme-panel)]'
              : 'from-white dark:from-zinc-950 lg:hidden'
          )}
        />
      )}
    </div>
  );
}

export default TripSummaryPills;
