'use client';

import type { Dispatch, SetStateAction } from 'react';

import { guardedGeneratePlan, PLAN_ACTIVE_STATES } from '@/components/plan/planStateHelpers';
import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { TripSettingsSheet } from '@/components/plan/sheets/TripSettingsSheet';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { SheetType } from '@/types/sheets';

interface LandingPreferenceSheetsProps {
  tripInputs: DocumentTripInputs;
  hasDestination: boolean;
  hasOrigin: boolean;
  hasDates: boolean;
  activeSheet: SheetType | null;
  gearActivitiesSheetOpen: boolean;
  gearStaysSheetOpen: boolean;
  gearFlightsSheetOpen: boolean;
  activityUserSaved: boolean;
  setActivityUserSaved: Dispatch<SetStateAction<boolean>>;
  setGearActivitiesSheetOpen: (open: boolean) => void;
  setGearStaysSheetOpen: (open: boolean) => void;
  setGearFlightsSheetOpen: (open: boolean) => void;
  closeSheet: () => void;
  openSheet: (name: SheetType) => void;
  addToast: (message: string, type?: ToastType) => void;
  storeUpdateTripInputs: (inputs: Partial<DocumentTripInputs>) => void;
  storeCommitTripInputs: (inputs: Partial<DocumentTripInputs>) => Promise<boolean>;
  handleUpdateActivitySettings: (
    settings: NonNullable<DocumentTripInputs['activity_settings']>
  ) => void;
  onSendMessage: (msg: string) => void;
}

export function LandingPreferenceSheets({
  tripInputs,
  hasDestination,
  hasOrigin,
  hasDates,
  activeSheet,
  gearActivitiesSheetOpen,
  gearStaysSheetOpen,
  gearFlightsSheetOpen,
  activityUserSaved,
  setActivityUserSaved,
  setGearActivitiesSheetOpen,
  setGearStaysSheetOpen,
  setGearFlightsSheetOpen,
  closeSheet,
  openSheet,
  addToast,
  storeUpdateTripInputs,
  storeCommitTripInputs,
  handleUpdateActivitySettings,
  onSendMessage,
}: LandingPreferenceSheetsProps) {
  return (
    <>
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
        onToggle={() => {}}
        onSaveSettings={async (settings) => {
          setActivityUserSaved(true);
          handleUpdateActivitySettings(settings);

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
            await storeCommitTripInputs({
              activity_settings: settings,
              ...(nextBookingTypes ? { booking_types: nextBookingTypes } : {}),
            });
            setGearActivitiesSheetOpen(false);
            closeSheet();
            addToast('Activity preferences saved', 'confirmation');
            const currentPVS = useDocumentStore.getState().document?.plan_view_state;
            if (PLAN_ACTIVE_STATES.has(currentPVS ?? '')) {
              // Gate the BUILD on dates — when missing, open the Dates sheet
              // and nudge instead of building a dateless plan (principle B).
              // willRebuild (S3) implies dates already exist, so deferral here
              // only occurs at S2 where willRebuild is false.
              guardedGeneratePlan({
                tripInputs: useDocumentStore.getState().document?.trip_inputs,
                sendBuild: () => onSendMessage(GENERATE_PLAN_TRIGGER),
                openDates: () => openSheet('dates'),
                addNudge: (text) =>
                  useChatStore.getState().addMessage({
                    id: `a_ui_${Date.now()}`,
                    role: 'assistant',
                    content: text,
                  }),
              });
            } else if (willRebuild) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
            }
          } catch {
            if (willRebuild) {
              useDocumentStore.getState().setRegenerationState({ isRegenerating: false });
            }
            addToast('Failed to save — please try again', 'error');
          }
        }}
      />

      <StaysSheet
        open={gearStaysSheetOpen}
        onOpenChange={setGearStaysSheetOpen}
        enabled={true}
        settings={tripInputs.hotel_settings || { min_stars: 0, amenities: [] }}
        hasDestination={hasDestination}
        hasDates={hasDates}
        onToggle={() => {}}
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
        onToggle={() => {}}
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

      <TripSettingsSheet
        open={activeSheet === 'trip-settings'}
        onOpenChange={(open) => !open && closeSheet()}
        tripInputs={tripInputs}
        onOpenSheet={openSheet}
      />
    </>
  );
}
