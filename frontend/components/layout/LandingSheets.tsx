'use client';

import { useState } from 'react';

import { LandingPreferenceSheets } from '@/components/layout/LandingPreferenceSheets';
import { LandingPrimarySheets } from '@/components/layout/LandingPrimarySheets';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface LandingSheetsProps {
  tripInputs: DocumentTripInputs;
  hasDestination: boolean;
  hasOrigin: boolean;
  hasDates: boolean;
  planViewState: PlanViewState | undefined;
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
  handleUpdateActivitySettings,
  onSendMessage,
}: LandingSheetsProps) {
  const [activityUserSaved, setActivityUserSaved] = useState(false);

  return (
    <>
      <LandingPrimarySheets
        tripInputs={tripInputs}
        planViewState={planViewState}
        activeSheet={activeSheet}
        closeSheet={closeSheet}
        addToast={addToast}
        storeUpdateTripInputs={storeUpdateTripInputs}
        storeCommitTripInputs={storeCommitTripInputs}
        onSendMessage={onSendMessage}
      />

      <LandingPreferenceSheets
        tripInputs={tripInputs}
        hasDestination={hasDestination}
        hasOrigin={hasOrigin}
        hasDates={hasDates}
        activeSheet={activeSheet}
        gearActivitiesSheetOpen={gearActivitiesSheetOpen}
        gearStaysSheetOpen={gearStaysSheetOpen}
        gearFlightsSheetOpen={gearFlightsSheetOpen}
        activityUserSaved={activityUserSaved}
        setActivityUserSaved={setActivityUserSaved}
        setGearActivitiesSheetOpen={setGearActivitiesSheetOpen}
        setGearStaysSheetOpen={setGearStaysSheetOpen}
        setGearFlightsSheetOpen={setGearFlightsSheetOpen}
        closeSheet={closeSheet}
        openSheet={openSheet}
        addToast={addToast}
        storeUpdateTripInputs={storeUpdateTripInputs}
        storeCommitTripInputs={storeCommitTripInputs}
        handleUpdateActivitySettings={handleUpdateActivitySettings}
        onSendMessage={onSendMessage}
      />
    </>
  );
}
