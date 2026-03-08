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

import { PLAN_ACTIVE_STATES } from '@/components/plan/planStateHelpers';
import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { triggerRegeneration } from '@/hooks/usePreferenceAutoRegen';
import { GENERATE_PLAN_TRIGGER } from '@/state/chatStore';
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
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
  // planViewState read from store at save time (prop may be stale after PATCH)
  planViewState: _planViewState,
  origin,
  hasDestination,
  hasDates,
  onUpdateBookingTypes,
  onUpdateFlightSettings,
  onUpdateHotelSettings,
  onUpdateActivitySettings: _onUpdateActivitySettings,
  onOpenSheet,
  sendMessageCore,
  toast,
  flightsSheetOpen,
  setFlightsSheetOpen,
  staysSheetOpen,
  setStaysSheetOpen,
  activitiesSheetOpen,
  setActivitiesSheetOpen,
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
          // No toast here — FlightsSheet.handleToggle and handleUpdateBookingTypes
          // already provide toggle feedback.
          // Trigger rebuild to fetch/remove flight tiles
          if (enabled) {
            const currentPVS = useDocumentStore.getState().document?.plan_view_state;
            if (PLAN_ACTIVE_STATES.has(currentPVS ?? '')) {
              void sendMessageCore(GENERATE_PLAN_TRIGGER);
            }
          }
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
          // Read CURRENT planViewState from store (prop may be stale after PATCH)
          const currentStaysPVS = useDocumentStore.getState().document?.plan_view_state;
          const isS3Stays = ['S3_ITINERARY_READY', 'S3_EDITING'].includes(currentStaysPVS ?? '');
          const isS2Stays = currentStaysPVS === 'S2_STRATEGY_READY';
          if (isS3Stays) {
            triggerRegeneration(true);
          } else if (isS2Stays) {
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
        hasExplicitSettings={activityUserSaved}
        hasDestination={hasDestination}
        onToggle={(enabled) => {
          if (onUpdateBookingTypes) {
            onUpdateBookingTypes({ activities: enabled ? 'on' : 'off' });
          }
          toast(enabled ? 'Activities included' : 'Activities removed');
        }}
        onSaveSettings={async (settings) => {
          setActivityUserSaved(true);

          // Early visual feedback: show rebuild overlay immediately if we'll
          // need a regeneration (S3).  Without this, the timeline stays static
          // during the commitTripInputs PATCH round-trip.
          const earlyPVS = useDocumentStore.getState().document?.plan_view_state;
          const willRebuild = ['S3_ITINERARY_READY', 'S3_EDITING'].includes(earlyPVS ?? '');
          if (willRebuild) {
            useDocumentStore.getState().setRegenerationState({ isRegenerating: true });
          }

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

          // Single atomic commit — commitTripInputs handles both the
          // optimistic local store update and the backend PATCH in one call.
          // Do NOT call onUpdateActivitySettings or updateTripInputs separately;
          // those would trigger redundant local writes and a debounced PATCH.
          await commitTripInputs({
            activity_settings: {
              ...settings,
              categories: settings.categories ?? [],
              day_preferences: settings.categories?.length ? (settings.day_preferences ?? {}) : {},
            },
            ...(nextBookingTypes ? { booking_types: nextBookingTypes } : {}),
          });

          toast('Activity preferences saved');
          // Read CURRENT planViewState from store (prop may be stale after PATCH)
          const currentPVS = useDocumentStore.getState().document?.plan_view_state;
          const isS3Activities = ['S3_ITINERARY_READY', 'S3_EDITING'].includes(currentPVS ?? '');
          const isS2Activities = currentPVS === 'S2_STRATEGY_READY';
          if (isS3Activities) {
            // Deterministic rebuild — re-search activity tiles + rebuild itinerary.
            // No agent, no LLM, ~2-3s instead of ~15s.
            const cats = settings.categories?.length ? settings.categories : undefined;
            triggerRegeneration(true, cats);
          } else {
            // Not S3 — reset the early visual flag if we set it
            if (willRebuild) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
            }
            if (isS2Activities) {
              sendMessageCore(GENERATE_PLAN_TRIGGER);
            }
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
