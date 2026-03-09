'use client';

import { memo, useCallback } from 'react';

import { UnifiedChipRow } from '@/components/plan/UnifiedChipRow';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { DEFAULT_BOOKING_TYPES } from '@/state/documentStore';
import type {
  ActivitySettings,
  BookingTypes,
  DocumentTripInputs,
  FlightSettings,
  HotelSettings,
} from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

import { getChatStatusConfig } from './ChatStatusHeader';

interface ChatBootstrapHeroProps {
  planViewState: PlanViewState | undefined | null;
  planState?: 'INCOMPLETE' | 'RESOLVING' | 'STABLE' | 'LOCKED';
  isGenerating: boolean;
  isFraming?: boolean;
  destination?: string;
  origin?: string;
  hasDates: boolean;
  dateRange?: string;
  budget?: string;
  tripInputs?: DocumentTripInputs;
  bookingTypes?: BookingTypes;
  flightSettings?: FlightSettings;
  hotelSettings?: HotelSettings;
  activitySettings?: ActivitySettings;
  onOpenSheet?: (sheet: SheetType) => void;
  onOpenModuleSheet: (sheet: 'flights' | 'stays' | 'activities' | null) => void;
}

function ChatBootstrapHeroInner({
  planViewState,
  planState,
  isGenerating,
  isFraming,
  destination,
  origin,
  hasDates,
  dateRange,
  budget,
  tripInputs,
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  onOpenSheet,
  onOpenModuleSheet,
}: ChatBootstrapHeroProps) {
  const status = getChatStatusConfig(planViewState, planState, isGenerating, destination, hasDates, isFraming);

  const onOpenFlights = useCallback(() => onOpenModuleSheet('flights'), [onOpenModuleSheet]);
  const onOpenStays = useCallback(() => onOpenModuleSheet('stays'), [onOpenModuleSheet]);
  const onOpenActivities = useCallback(() => onOpenModuleSheet('activities'), [onOpenModuleSheet]);

  return (
    <>
      {/* Hero banner — scrolls up as messages arrive */}
      <div className="flex flex-col items-center justify-center text-center px-4 pb-4">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {status.text}
        </h1>
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className={cn(
            `font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-primary`,
            DS.glowClass.dropText,
          )}>
            {status.label}
          </span>
          <div className={cn(
            'h-1.5 w-1 animate-terminal-blink rounded-sm bg-primary',
            DS.glowClass.cursor,
          )} />
        </div>
      </div>
      {/* Unified Chip Row — scrolls with hero */}
      <UnifiedChipRow
        destination={destination}
        origin={origin}
        dateRange={dateRange}
        travelers={tripInputs?.adults ? `${tripInputs.adults} adult${tripInputs.adults > 1 ? 's' : ''}${tripInputs.children ? `, ${tripInputs.children} child${tripInputs.children > 1 ? 'ren' : ''}` : ''}` : undefined}
        budget={budget}
        bookingTypes={bookingTypes || DEFAULT_BOOKING_TYPES}
        flightSettings={flightSettings}
        hotelSettings={hotelSettings}
        activitySettings={activitySettings}
        onOpenDestination={() => onOpenSheet?.('destination')}
        onOpenOrigin={() => onOpenSheet?.('origin')}
        onOpenDates={() => onOpenSheet?.('dates')}
        onOpenTravelers={() => onOpenSheet?.('travelers')}
        onOpenBudget={() => onOpenSheet?.('budget')}
        onOpenFlights={onOpenFlights}
        onOpenStays={onOpenStays}
        onOpenActivities={onOpenActivities}
        destinationLocked={!!destination}
      />
      {/* Divider between setup controls and conversation */}
      <div className="mx-auto mb-4 mt-6 w-2/3 border-t border-border/50" />
    </>
  );
}

export const ChatBootstrapHero = memo(ChatBootstrapHeroInner);
