'use client';

import { PLAN_ACTIVE_STATES } from '@/components/plan/planStateHelpers';
import { BudgetSheet } from '@/components/plan/sheets/BudgetSheet';
import { DatesSheet } from '@/components/plan/sheets/DatesSheet';
import { DestinationSheet } from '@/components/plan/sheets/DestinationSheet';
import { OriginSheet } from '@/components/plan/sheets/OriginSheet';
import { TravelersSheet } from '@/components/plan/sheets/TravelersSheet';
import { parseISODateLocal } from '@/lib/date-utils';
import { GENERATE_PLAN_TRIGGER } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import type { DocumentTripInputs } from '@/types/document';
import type { ToastType } from '@/types/hooks';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';

interface LandingPrimarySheetsProps {
  tripInputs: DocumentTripInputs;
  planViewState: PlanViewState | undefined;
  activeSheet: SheetType | null;
  closeSheet: () => void;
  addToast: (message: string, type?: ToastType) => void;
  storeUpdateTripInputs: (inputs: Partial<DocumentTripInputs>) => void;
  storeCommitTripInputs: (inputs: Partial<DocumentTripInputs>) => Promise<boolean>;
  onSendMessage: (msg: string) => void;
}

export function LandingPrimarySheets({
  tripInputs,
  planViewState,
  activeSheet,
  closeSheet,
  addToast,
  storeUpdateTripInputs,
  storeCommitTripInputs,
  onSendMessage,
}: LandingPrimarySheetsProps) {
  return (
    <>
      <DestinationSheet
        open={activeSheet === 'destination' && !tripInputs.destination}
        onOpenChange={(open) => !open && closeSheet()}
        value={tripInputs.destination || ''}
        onSave={async (value) => {
          storeUpdateTripInputs({ destination: value });
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
          const currentBT = useDocumentStore.getState().document?.trip_inputs?.booking_types;
          const updates: Partial<DocumentTripInputs> = { origin: value };
          if (currentBT && currentBT.flights === 'off') {
            updates.booking_types = { ...currentBT, flights: 'suggested' };
          }
          storeUpdateTripInputs(updates);
          try {
            await storeCommitTripInputs(updates);
            closeSheet();
            addToast(`Origin: ${value}`, 'confirmation');
            if (planViewState && PLAN_ACTIVE_STATES.has(planViewState)) {
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
          const startStr = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
          const endStr = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, '0')}-${String(end.getDate()).padStart(2, '0')}`;
          storeUpdateTripInputs({
            start_date: startStr,
            end_date: endStr,
          });
          try {
            await storeCommitTripInputs({
              start_date: startStr,
              end_date: endStr,
            });
            closeSheet();
            addToast(`Dates: ${startStr} to ${endStr}`, 'confirmation');
            if (planViewState && PLAN_ACTIVE_STATES.has(planViewState)) {
              onSendMessage(GENERATE_PLAN_TRIGGER);
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
          storeUpdateTripInputs({ adults, children });
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
          storeUpdateTripInputs({ budget: amount, currency });
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
    </>
  );
}
