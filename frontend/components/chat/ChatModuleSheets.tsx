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
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
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
import type { Tile } from '@/types/tile';

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
  const patchDocument = useDocumentStore((s) => s.patchDocument);
  const updateTripInputs = useDocumentStore((s) => s.updateTripInputs);
  const commitTripInputs = useDocumentStore((s) => s.commitTripInputs);

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
        onSaveSettings={async (settings) => {
          const prevDayPrefs = activitySettings?.day_preferences || {};
          const prevCats = new Set(activitySettings?.categories || []);
          const newCats = new Set(settings.categories || []);

          // D3: Prune preferred_tile_ids for tiles belonging to removed categories.
          // Hearted tiles from a removed category would otherwise be placed by
          // Phase 5.25 even when the user has switched away from that activity.
          const removedCats = [...prevCats].filter(c => !newCats.has(c));
          const { document: planDocument, version: docVersion } = useDocumentStore.getState();
          if (removedCats.length > 0 && planDocument) {
            const currentPreferred = planDocument.preferred_tile_ids ?? [];
            const tiles = planDocument.tiles ?? {};
            const removedCatSet = new Set(removedCats.map(c => c.toLowerCase()));
            const prunedPreferred = currentPreferred.filter((tileId) => {
              const tile = tiles[tileId] as Tile | undefined;
              if (!tile) return true; // Unknown tile — keep
              const tileCategory = (
                (tile.meta?.specialist_type as string | undefined)
                ?? (tile.meta?.category as string | undefined)
                ?? ''
              ).toLowerCase();
              const tileTags = new Set((tile.tags ?? []).map(t => t.toLowerCase()));
              const isRemovedCategory =
                (tileCategory && removedCatSet.has(tileCategory))
                || [...tileTags].some(t => removedCatSet.has(t));
              return !isRemovedCategory;
            });
            if (prunedPreferred.length !== currentPreferred.length) {
              patchDocument({ version: docVersion, preferred_tile_ids: prunedPreferred });
            }
          }

          const shouldDisableActivities = (settings.categories?.length ?? 0) === 0;
          const nextBookingTypes = shouldDisableActivities
            ? {
                ...DEFAULT_BOOKING_TYPES,
                ...(useDocumentStore.getState().document?.trip_inputs?.booking_types ?? {}),
                activities: 'off' as const,
              }
            : undefined;

          onUpdateActivitySettings?.(settings);
          if (nextBookingTypes) {
            updateTripInputs({ booking_types: nextBookingTypes });
          }

          await commitTripInputs({
            activity_settings: {
              ...settings,
              categories: settings.categories ?? [],
              day_preferences: settings.categories?.length ? (settings.day_preferences ?? {}) : {},
            },
            ...(nextBookingTypes ? { booking_types: nextBookingTypes } : {}),
          });

          toast('Activity preferences saved');
          const isActive = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
            planViewState ?? ''
          );
          if (isActive) {
            const newDayPrefs = settings.day_preferences || {};
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
