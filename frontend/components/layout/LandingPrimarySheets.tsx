'use client';

import {
  guardedGeneratePlan,
  PLAN_ACTIVE_STATES,
  shouldAutoTriggerItinerary,
} from '@/components/plan/planStateHelpers';
import { BudgetSheet } from '@/components/plan/sheets/BudgetSheet';
import { DatesSheet } from '@/components/plan/sheets/DatesSheet';
import { DestinationSheet } from '@/components/plan/sheets/DestinationSheet';
import { OriginSheet } from '@/components/plan/sheets/OriginSheet';
import { TravelersSheet } from '@/components/plan/sheets/TravelersSheet';
import { parseISODateLocal } from '@/lib/date-utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
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
  openSheet: (name: SheetType) => void;
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
  openSheet,
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
              // Gate the BUILD on dates — origin can be set at S2 (no dates).
              // Defer to the Dates sheet instead of building dateless (principle B).
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
            // Read PVS FRESH from the store — the `planViewState` prop is
            // prerequisite-gated and is null/undefined at the exact moment the
            // user is adding the missing dates (see useLandingDerived). The
            // dates we just committed are already in the store here.
            const freshDoc = useDocumentStore.getState().document;
            const currentPVS = freshDoc?.plan_view_state;
            if (currentPVS && PLAN_ACTIVE_STATES.has(currentPVS)) {
              // AVOID DOUBLE-BUILD: for multi-specialist trips the auto-trigger
              // effect (useItineraryGenerationController) ALSO fires a build via
              // /api/expand-itinerary once dates flip true. Only fire our trigger
              // when that auto-trigger will NOT handle it.
              const willAutoTrigger = shouldAutoTriggerItinerary(
                currentPVS,
                freshDoc?.executed_strategy_topics,
                true, // dates just committed above
                null, // not generating yet
                (freshDoc?.day_cards?.length ?? 0) > 0
              );
              if (!willAutoTrigger) {
                // Gate the BUILD on dates via the tested helper — dates are
                // already committed so it fires sendBuild; if somehow absent it
                // defers to the Dates sheet (keeps the dateless-build invariant).
                guardedGeneratePlan({
                  tripInputs: freshDoc?.trip_inputs,
                  sendBuild: () => onSendMessage(GENERATE_PLAN_TRIGGER),
                  openDates: () => openSheet('dates'),
                  addNudge: (text) =>
                    useChatStore.getState().addMessage({
                      id: `a_ui_${Date.now()}`,
                      role: 'assistant',
                      content: text,
                    }),
                });
              }
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
