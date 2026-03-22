'use client';

import type { ReactNode } from 'react';

import type { ChatMessage } from '@/types/chat';
import type { ActivitySettings, BookingTypes, DocumentTripInputs,FlightSettings, HotelSettings } from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

import { ChatBootstrapHero } from './ChatBootstrapHero';
import type { ActiveStatus } from './SmartLoader';
import { SmartLoader } from './SmartLoader';

// ─────────────────────────────────────────────────────────────────────────────
// ActiveLoaderSection — renders the contextual SmartLoader above suggestions
// ─────────────────────────────────────────────────────────────────────────────

interface ActiveLoaderSectionProps {
  isRegenerating: boolean;
  isLoading: boolean;
  activeStatus: ActiveStatus | null;
  visibleMessages: ChatMessage[];
}

export function ActiveLoaderSection({
  isRegenerating,
  isLoading,
  activeStatus,
  visibleMessages,
}: ActiveLoaderSectionProps) {
  if (isRegenerating) {
    return (
      <SmartLoader
        status={{ label: 'REBUILDING ITINERARY', icon_key: 'calendar' }}
      />
    );
  }

  if (
    isLoading &&
    activeStatus &&
    visibleMessages[visibleMessages.length - 1]?.role === 'user'
  ) {
    return <SmartLoader status={activeStatus} />;
  }

  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// buildScrollHeaderContent — builds the ChatBootstrapHero element for message list
// ─────────────────────────────────────────────────────────────────────────────

interface ScrollHeaderContentArgs {
  showBootstrapHero: boolean;
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

export function buildScrollHeaderContent(args: ScrollHeaderContentArgs): ReactNode | undefined {
  if (!args.showBootstrapHero) return undefined;

  return (
    <ChatBootstrapHero
      planViewState={args.planViewState}
      planState={args.planState}
      isGenerating={args.isGenerating}
      isFraming={args.isFraming}
      destination={args.destination}
      origin={args.origin}
      hasDates={args.hasDates}
      dateRange={args.dateRange}
      budget={args.budget}
      tripInputs={args.tripInputs}
      bookingTypes={args.bookingTypes}
      flightSettings={args.flightSettings}
      hotelSettings={args.hotelSettings}
      activitySettings={args.activitySettings}
      onOpenSheet={args.onOpenSheet}
      onOpenModuleSheet={args.onOpenModuleSheet}
    />
  );
}
