'use client';

/**
 * ChatModuleSheets — Flights / Stays / Activities sheet rendering.
 *
 * Extracted from ChatPanel to keep the parent component focused on
 * layout and message orchestration. Contains the inline onToggle,
 * onSaveSettings, and cross-sheet navigation callbacks.
 */

import { useEffect, useRef } from 'react';

import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { GENERATE_PLAN_TRIGGER } from '@/state/chatStore';
import type { AckUpdate , ChatMessage } from '@/types/chat';
import type {
  ActivitySettings,
  BookingTypes,
  FlightSettings,
  HotelSettings,
} from '@/types/document';
import { isBookingEnabled } from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface ChatModuleSheetsProps {
  // Settings
  bookingTypes?: BookingTypes;
  flightSettings?: FlightSettings;
  hotelSettings?: HotelSettings;
  activitySettings?: ActivitySettings;
  planViewState?: PlanViewState;

  // Gating
  origin?: string;
  hasDestination: boolean;
  hasDates: boolean;

  // Callbacks
  onUpdateBookingTypes?: (updates: Partial<BookingTypes>) => void;
  onUpdateFlightSettings?: (updates: Partial<FlightSettings>) => void;
  onUpdateHotelSettings?: (updates: Partial<HotelSettings>) => void;
  onUpdateActivitySettings?: (updates: Partial<ActivitySettings>) => void;
  onOpenSheet?: (sheet: SheetType) => void;

  // Core actions
  sendMessageCore: (messageText: string, options?: { suggestionClicked?: string }) => Promise<void>;
  addMessage: (msg: ChatMessage) => void;
  toast: (message: string) => void;

  // Open state (controlled from parent)
  flightsSheetOpen: boolean;
  setFlightsSheetOpen: (v: boolean) => void;
  staysSheetOpen: boolean;
  setStaysSheetOpen: (v: boolean) => void;
  activitiesSheetOpen: boolean;
  setActivitiesSheetOpen: (v: boolean) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function ChatModuleSheets({
  bookingTypes,
  flightSettings,
  hotelSettings,
  activitySettings,
  planViewState,
  origin,
  hasDestination,
  hasDates,
  onUpdateBookingTypes,
  onUpdateFlightSettings,
  onUpdateHotelSettings,
  onUpdateActivitySettings,
  onOpenSheet,
  sendMessageCore,
  addMessage,
  toast,
  flightsSheetOpen,
  setFlightsSheetOpen,
  staysSheetOpen,
  setStaysSheetOpen,
  activitiesSheetOpen,
  setActivitiesSheetOpen,
}: ChatModuleSheetsProps) {
  const sheetOpenTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (sheetOpenTimeoutRef.current) clearTimeout(sheetOpenTimeoutRef.current);
    };
  }, []);

  return (
    <>
      <FlightsSheet
        open={flightsSheetOpen}
        onOpenChange={setFlightsSheetOpen}
        enabled={isBookingEnabled(bookingTypes?.flights)}
        settings={flightSettings || { round_trip: true, cabin_class: 'economy', direct_only: false }}
        hasOrigin={!!origin}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={(enabled) => {
          if (onUpdateBookingTypes) {
            onUpdateBookingTypes({ flights: enabled ? 'on' : 'off' });
          }
          toast(enabled ? 'Flights included' : 'Flights removed');
        }}
        onSaveSettings={(settings) => {
          if (onUpdateFlightSettings) {
            onUpdateFlightSettings(settings);
          }
          toast('Flight preferences saved');
        }}
        onOpenOrigin={() => {
          setFlightsSheetOpen(false);
          sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('origin'), 150);
        }}
        onOpenDestination={() => {
          setFlightsSheetOpen(false);
          sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('destination'), 150);
        }}
        onOpenDates={() => {
          setFlightsSheetOpen(false);
          sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('dates'), 150);
        }}
      />

      <StaysSheet
        open={staysSheetOpen}
        onOpenChange={setStaysSheetOpen}
        enabled={isBookingEnabled(bookingTypes?.hotels)}
        settings={hotelSettings || { min_stars: 0, amenities: [] }}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={(enabled) => {
          if (onUpdateBookingTypes) {
            onUpdateBookingTypes({ hotels: enabled ? 'on' : 'off' });
          }
          toast(enabled ? 'Stays included' : 'Stays removed');
        }}
        onSaveSettings={(settings) => {
          if (onUpdateHotelSettings) {
            onUpdateHotelSettings(settings);
          }
          toast('Stay preferences saved');
          const isActive = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
            planViewState ?? ''
          );
          if (isActive) {
            const updates: AckUpdate[] = [];
            if (settings.min_stars) updates.push({ field: 'hotels', to: `${settings.min_stars}+ stars` });
            if (updates.length > 0) {
              addMessage({ id: `sys_ack_${Date.now()}`, role: 'system', content: '', displayMode: 'ack_line', ackStatus: 'applied', ackUpdates: updates });
            }
            sendMessageCore(GENERATE_PLAN_TRIGGER);
          }
        }}
        onOpenDestination={() => {
          setStaysSheetOpen(false);
          sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('destination'), 150);
        }}
        onOpenDates={() => {
          setStaysSheetOpen(false);
          sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('dates'), 150);
        }}
      />

      <ActivitiesSheet
        open={activitiesSheetOpen}
        onOpenChange={setActivitiesSheetOpen}
        enabled={isBookingEnabled(bookingTypes?.activities)}
        settings={activitySettings || { categories: [], skill_level: null }}
        hasDestination={hasDestination}
        onToggle={(enabled) => {
          if (onUpdateBookingTypes) {
            onUpdateBookingTypes({ activities: enabled ? 'on' : 'off' });
          }
          toast(enabled ? 'Activities included' : 'Activities removed');
        }}
        onSaveSettings={(settings) => {
          const prevDayPrefs = activitySettings?.day_preferences || {};
          const prevCats = new Set(activitySettings?.categories || []);
          onUpdateActivitySettings?.(settings);
          toast('Activity preferences saved');
          const isActive = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
            planViewState ?? ''
          );
          if (isActive) {
            const newDayPrefs = settings.day_preferences || {};
            const newCats = new Set(settings.categories || []);
            const updates: AckUpdate[] = [];
            for (const cat of newCats) {
              if (!prevCats.has(cat)) {
                updates.push({ field: cat, to: 'added' });
              }
            }
            for (const cat of prevCats) {
              if (!newCats.has(cat)) {
                updates.push({ field: cat, to: 'removed' });
              }
            }
            for (const [topic, newVal] of Object.entries(newDayPrefs)) {
              const prevVal = prevDayPrefs[topic];
              if (prevVal !== undefined && prevVal !== newVal) {
                updates.push({ field: topic, to: `${newVal} days`, from_value: `${prevVal} days` });
              } else if (prevVal === undefined) {
                updates.push({ field: topic, to: `${newVal} days` });
              }
            }
            if (updates.length > 0) {
              addMessage({ id: `sys_ack_${Date.now()}`, role: 'system', content: '', displayMode: 'ack_line', ackStatus: 'applied', ackUpdates: updates });
            }
            sendMessageCore(GENERATE_PLAN_TRIGGER);
          }
        }}
        onOpenDestination={() => {
          setActivitiesSheetOpen(false);
          sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('destination'), 150);
        }}
      />
    </>
  );
}
