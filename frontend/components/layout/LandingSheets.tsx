'use client';

import { useState } from 'react';

import { PLAN_ACTIVE_STATES } from '@/components/plan/planStateHelpers';
import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { BudgetSheet } from '@/components/plan/sheets/BudgetSheet';
import { DatesSheet } from '@/components/plan/sheets/DatesSheet';
import { DestinationSheet } from '@/components/plan/sheets/DestinationSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { OriginSheet } from '@/components/plan/sheets/OriginSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { TravelersSheet } from '@/components/plan/sheets/TravelersSheet';
import { TripSettingsSheet } from '@/components/plan/sheets/TripSettingsSheet';
import { parseISODateLocal } from '@/lib/date-utils';
import { GENERATE_PLAN_TRIGGER } from '@/state/chatStore';
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface LandingSheetsProps {
  tripInputs: DocumentTripInputs;
  hasDestination: boolean;
  hasOrigin: boolean;
  hasDates: boolean;
  planViewState: PlanViewState;
  activeSheet: SheetType | null;
  gearActivitiesSheetOpen: boolean;
  gearStaysSheetOpen: boolean;
  gearFlightsSheetOpen: boolean;
  setGearActivitiesSheetOpen: (open: boolean) => void;
  setGearStaysSheetOpen: (open: boolean) => void;
  setGearFlightsSheetOpen: (open: boolean) => void;
  closeSheet: () => void;
  openSheet: (name: SheetType) => void;
  addToast: (message: string, type?: ToastType) => void;
  storeUpdateTripInputs: (inputs: Partial<DocumentTripInputs>) => void;
  storeCommitTripInputs: (inputs: Partial<DocumentTripInputs>) => Promise<boolean>;
  hasItinerary: boolean;
  proceedWithItineraryGeneration: (options?: { forceFullRebuild?: boolean }) => Promise<void>;
  handleUpdateActivitySettings: (settings: NonNullable<DocumentTripInputs['activity_settings']>) => void;
  onSendMessage: (msg: string) => void;
}

export function LandingSheets({
  tripInputs,
  hasDestination,
  hasOrigin,
  hasDates,
  planViewState,
  activeSheet,
  gearActivitiesSheetOpen,
  gearStaysSheetOpen,
  gearFlightsSheetOpen,
  setGearActivitiesSheetOpen,
  setGearStaysSheetOpen,
  setGearFlightsSheetOpen,
  closeSheet,
  openSheet,
  addToast,
  storeUpdateTripInputs,
  storeCommitTripInputs,
  hasItinerary,
  proceedWithItineraryGeneration,
  handleUpdateActivitySettings,
  onSendMessage,
}: LandingSheetsProps) {
  // Track whether the user has explicitly saved activity settings in this session.
  // When true, respect saved categories (even if empty) instead of inferring from day cards.
  const [activityUserSaved, setActivityUserSaved] = useState(false);

  return (
    <>
      {/* Trip input sheets - shared between header pills and chat panel */}
      {/* In S1+, header pills are the ONLY interactive surface for trip inputs */}
      {/* Destination sheet LOCKED once set - can only change via full trip reset */}
      <DestinationSheet
        open={activeSheet === 'destination' && !tripInputs.destination}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.destination || ''}
        onSave={async (value) => {
          // SYNC: Update store immediately so RefreshButton sees new value
          storeUpdateTripInputs({ destination: value });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ destination: value });
            closeSheet();
            addToast(`Destination: ${value}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <OriginSheet
        open={activeSheet === 'origin'}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.origin || ''}
        onSave={async (value) => {
          // Build atomic update: origin + flights upgrade in single PATCH
          const currentBT = useDocumentStore.getState().document?.trip_inputs?.booking_types;
          const updates: Partial<DocumentTripInputs> = { origin: value };
          if (currentBT && currentBT.flights === 'off') {
            updates.booking_types = { ...currentBT, flights: 'suggested' };
          }
          // SYNC: Update store immediately so RefreshButton sees new value
          storeUpdateTripInputs(updates);
          // ASYNC: Persist to backend (single PATCH)
          try {
            await storeCommitTripInputs(updates);
            closeSheet();
            addToast(`Origin: ${value}`, 'confirmation');
            // Trigger flight fetch via graph pipeline when plan is active
            const isActive = PLAN_ACTIVE_STATES.has(planViewState);
            if (isActive) {
              onSendMessage(GENERATE_PLAN_TRIGGER);
            }
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <DatesSheet
        open={activeSheet === 'dates'}
        onOpenChange={(open) => !open && closeSheet()}
        startDate={parseISODateLocal(tripInputs.start_date)}
        endDate={parseISODateLocal(tripInputs.end_date)}
        onSave={async (start, end) => {
          // Use local date components to avoid timezone shifts
          // toISOString() converts to UTC which can shift the date by a day
          const startStr = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
          const endStr = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`;
          // SYNC: Update store immediately so RefreshButton sees new value
          storeUpdateTripInputs({
            start_date: startStr,
            end_date: endStr,
          });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({
              start_date: startStr,
              end_date: endStr,
            });
            closeSheet();

            // Trigger itinerary rebuild if one exists
            if (hasItinerary) {
              proceedWithItineraryGeneration({ forceFullRebuild: true });
            }
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <TravelersSheet
        open={activeSheet === 'travelers'}
        onOpenChange={(open) => !open && closeSheet()}
        adults={tripInputs.adults ?? 1}
        children={tripInputs.children ?? 0}
        onSave={async (adults, children) => {
          // SYNC: Update store immediately
          storeUpdateTripInputs({ adults, children });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ adults, children });
            closeSheet();
            const label = `${adults} adult${adults > 1 ? 's' : ''}${children > 0 ? `, ${children} child${children > 1 ? 'ren' : ''}` : ''}`;
            addToast(`Travelers: ${label}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <BudgetSheet
        open={activeSheet === 'budget'}
        onOpenChange={(open) => !open && closeSheet()}
        amount={tripInputs.budget ?? null}
        currency={tripInputs.currency || 'USD'}
        budgetType="total"
        onSave={async (amount, currency) => {
          // SYNC: Update store immediately
          storeUpdateTripInputs({ budget: amount, currency });
          // ASYNC: Persist to backend
          try {
            await storeCommitTripInputs({ budget: amount, currency });
            closeSheet();
            const formatted = new Intl.NumberFormat('en-US', {
              style: 'currency',
              currency,
              maximumFractionDigits: 0,
            }).format(amount);
            addToast(`Budget: ${formatted}`, 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      {/* Activity settings sheet - opened from gear icons + Activities pill */}
      <ActivitiesSheet
        open={gearActivitiesSheetOpen || activeSheet === 'activities'}
        onOpenChange={(open) => {
          setGearActivitiesSheetOpen(open);
          if (!open) closeSheet();
        }}
        enabled={true}
        settings={tripInputs.activity_settings || { categories: [], skill_level: null }}
        hasExplicitSettings={activityUserSaved}
        hasDestination={hasDestination}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={async (settings) => {
          setActivityUserSaved(true);
          handleUpdateActivitySettings(settings);

          // Early visual feedback: show rebuild overlay immediately for S3.
          const earlyPVS = useDocumentStore.getState().document?.plan_view_state;
          const willRebuild = ['S3_ITINERARY_READY', 'S3_EDITING'].includes(earlyPVS ?? '');
          if (willRebuild) {
            useDocumentStore.getState().setRegenerationState({ isRegenerating: true });
          }

          try {
            const shouldDisableActivities = (settings.categories?.length ?? 0) === 0;
            const nextBookingTypes = shouldDisableActivities
              ? {
                  ...DEFAULT_BOOKING_TYPES,
                  ...(tripInputs.booking_types ?? {}),
                  activities: 'off' as const,
                }
              : undefined;
            if (nextBookingTypes) {
              storeUpdateTripInputs({ booking_types: nextBookingTypes });
            }
            // Ensure backend has the latest activity_settings before regeneration.
            await storeCommitTripInputs({
              activity_settings: settings,
              ...(nextBookingTypes ? { booking_types: nextBookingTypes } : {}),
            });
            setGearActivitiesSheetOpen(false);
            closeSheet();
            addToast('Activity preferences saved', 'confirmation');
            // Trigger full graph pipeline — activity category changes require
            // specialist re-dispatch (expand-itinerary only refreshes tiles
            // with existing strategy sections).
            const currentPVS = useDocumentStore.getState().document?.plan_view_state;
            if (PLAN_ACTIVE_STATES.has(currentPVS ?? '')) {
              onSendMessage(GENERATE_PLAN_TRIGGER);
            } else {
              // Not in an active plan state — clear early visual flag
              if (willRebuild) {
                useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
              }
            }
          } catch {
            // Reset early flag on error
            if (willRebuild) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
            }
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      {/* Stays settings sheet - opened from gear icons on hotel/check-in blocks */}
      <StaysSheet
        open={gearStaysSheetOpen}
        onOpenChange={setGearStaysSheetOpen}
        enabled={true}
        settings={tripInputs.hotel_settings || { min_stars: 0, amenities: [] }}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={async (settings) => {
          try {
            await storeCommitTripInputs({ hotel_settings: settings });
            setGearStaysSheetOpen(false);
            addToast('Hotel preferences saved', 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
        onOpenDestination={() => openSheet('destination')}
        onOpenDates={() => openSheet('dates')}
      />

      {/* Flights settings sheet - opened from gear icons on arrival/departure blocks */}
      <FlightsSheet
        open={gearFlightsSheetOpen}
        onOpenChange={setGearFlightsSheetOpen}
        enabled={true}
        settings={
          tripInputs.flight_settings || {
            round_trip: true,
            cabin_class: 'economy',
            direct_only: false,
          }
        }
        hasOrigin={hasOrigin}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={() => {}} // No-op - toggle handled by module toggle in ChatPanel
        onSaveSettings={async (settings) => {
          try {
            await storeCommitTripInputs({ flight_settings: settings });
            setGearFlightsSheetOpen(false);
            addToast('Flight preferences saved', 'confirmation');
          } catch {
            addToast('Failed to save — please try again', 'error');
          }
        }}
        onOpenOrigin={() => openSheet('origin')}
        onOpenDestination={() => openSheet('destination')}
        onOpenDates={() => openSheet('dates')}
      />

      {/* Trip settings relay sheet - opened from TripStatusBar pencil icon */}
      <TripSettingsSheet
        open={activeSheet === 'trip-settings'}
        onOpenChange={(open) => !open && closeSheet()}
        tripInputs={tripInputs}
        onOpenSheet={openSheet}
      />
    </>
  );
}
