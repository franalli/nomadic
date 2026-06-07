'use client';

/**
 * ChatModuleSheets — Flights / Stays / Activities sheet rendering.
 *
 * Extracted from ChatPanel to keep the parent component focused on
 * layout and message orchestration. Contains the inline onToggle,
 * onSaveSettings, and cross-sheet navigation callbacks.
 */

import { useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useDocumentStore } from '@/state/documentStore';
import type {
  ActivitySettings,
  BookingTypes,
  FlightSettings,
  HotelSettings,
} from '@/types/document';
import { isBookingEnabled } from '@/types/document';
import type { SheetType } from '@/types/sheets';

import {
  handleActivitiesSave,
  handleActivitiesToggle,
  handleFlightsSave,
  handleFlightsToggle,
  handleStaysSave,
  handleStaysToggle,
} from './chatModuleSheetHandlers';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface ChatModuleSheetsProps {
  bookingTypes?: BookingTypes;
  flightSettings?: FlightSettings;
  hotelSettings?: HotelSettings;
  activitySettings?: ActivitySettings;
  origin?: string;
  hasDestination: boolean;
  hasDates: boolean;
  onUpdateBookingTypes?: (updates: Partial<BookingTypes>) => void;
  onUpdateFlightSettings?: (updates: Partial<FlightSettings>) => void;
  onUpdateHotelSettings?: (updates: Partial<HotelSettings>) => void;
  onOpenSheet?: (sheet: SheetType) => void;
  sendMessageCore: (messageText: string, options?: { suggestionClicked?: string }) => Promise<void>;
  toast: (message: string) => void;
  openModuleSheet: 'flights' | 'stays' | 'activities' | null;
  setOpenModuleSheet: (v: 'flights' | 'stays' | 'activities' | null) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function ChatModuleSheets({
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  origin,
  hasDestination,
  hasDates,
  onUpdateBookingTypes,
  onUpdateFlightSettings,
  onUpdateHotelSettings,
  onOpenSheet,
  sendMessageCore,
  toast,
  openModuleSheet,
  setOpenModuleSheet,
}: ChatModuleSheetsProps) {
  const [activityUserSaved, setActivityUserSaved] = useState(false);
  const sheetOpenTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { patchDocument, commitTripInputs } = useDocumentStore(
    useShallow((s) => ({
      patchDocument: s.patchDocument,
      commitTripInputs: s.commitTripInputs,
    }))
  );

  useEffect(() => {
    return () => {
      if (sheetOpenTimeoutRef.current) clearTimeout(sheetOpenTimeoutRef.current);
    };
  }, []);

  const openSheetDelayed = (sheet: SheetType) => {
    setOpenModuleSheet(null);
    sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.(sheet), 150);
  };

  // Open the Dates sheet when a plan BUILD is deferred for missing dates.
  const openDates = () => onOpenSheet?.('dates');

  return (
    <>
      <ErrorBoundary label="Flights">
        <FlightsSheet
          open={openModuleSheet === 'flights'}
          onOpenChange={(v) => setOpenModuleSheet(v ? 'flights' : null)}
          enabled={isBookingEnabled(bookingTypes?.flights)}
          settings={flightSettings || { round_trip: true, cabin_class: 'economy', direct_only: false }}
          hasOrigin={!!origin}
          hasDestination={hasDestination}
          hasDates={hasDates}
          onToggle={(enabled) => handleFlightsToggle(enabled, onUpdateBookingTypes, sendMessageCore, openDates)}
          onSaveSettings={(settings) => handleFlightsSave(settings, onUpdateFlightSettings, toast)}
          onOpenOrigin={() => openSheetDelayed('origin')}
          onOpenDestination={() => openSheetDelayed('destination')}
          onOpenDates={() => openSheetDelayed('dates')}
        />
      </ErrorBoundary>

      <ErrorBoundary label="Stays">
        <StaysSheet
          open={openModuleSheet === 'stays'}
          onOpenChange={(v) => setOpenModuleSheet(v ? 'stays' : null)}
          enabled={isBookingEnabled(bookingTypes?.hotels)}
          settings={hotelSettings || { min_stars: 0, amenities: [] }}
          hasDestination={hasDestination}
          hasDates={hasDates}
          onToggle={(enabled) => handleStaysToggle(enabled, onUpdateBookingTypes, toast)}
          onSaveSettings={(settings) => handleStaysSave(settings, onUpdateHotelSettings, toast, sendMessageCore, openDates)}
          onOpenDestination={() => openSheetDelayed('destination')}
          onOpenDates={() => openSheetDelayed('dates')}
        />
      </ErrorBoundary>

      <ErrorBoundary label="Activities">
        <ActivitiesSheet
          open={openModuleSheet === 'activities'}
          onOpenChange={(v) => setOpenModuleSheet(v ? 'activities' : null)}
          enabled={isBookingEnabled(bookingTypes?.activities)}
          settings={activitySettings || { categories: [], skill_level: null }}
          hasExplicitSettings={activityUserSaved}
          hasDestination={hasDestination}
          onToggle={(enabled) => handleActivitiesToggle(enabled, onUpdateBookingTypes, toast)}
          onSaveSettings={(settings) =>
            handleActivitiesSave(
              settings,
              activitySettings,
              setActivityUserSaved,
              patchDocument,
              commitTripInputs,
              sendMessageCore,
              toast,
              openDates,
            )
          }
          onOpenDestination={() => openSheetDelayed('destination')}
        />
      </ErrorBoundary>
    </>
  );
}
