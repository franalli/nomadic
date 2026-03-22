/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { useShallow } from 'zustand/react/shallow';

import { useDocumentStore } from '@/state/documentStore';
import type {
  BookingTypes,
  FlightSettings,
  SuggestionChip,
  SuggestionChipMeta,
} from '@/types/document';
import type { SheetType } from '@/types/sheets';

import { DateFlexChip } from './DateFlexChip';
import { resolveChipAction,SuggestionChipItem } from './SuggestionChipItem';

interface ChatSuggestionChipsProps {
  effectiveSuggestions: string[];
  suggestionChips: SuggestionChip[];
  suggestedResponseMeta: SuggestionChipMeta[];
  isLoading: boolean;
  bookingTypes?: BookingTypes;
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  onOpenSheet?: (sheet: SheetType) => void;
  onSendMessage: (message: string, options?: { suggestionClicked?: string }) => void;
  onConfirmReset?: () => void;
  onOpenFlights: () => void;
  onOpenStays: () => void;
  onOpenActivities: () => void;
  toast: (message: string) => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────

export function ChatSuggestionChips({
  effectiveSuggestions,
  suggestionChips,
  suggestedResponseMeta,
  isLoading,
  bookingTypes,
  onUpdateFlightSettings,
  onUpdateBookingTypes,
  onConfirmReset,
  onOpenSheet,
  onSendMessage,
  onOpenFlights,
  onOpenStays,
  onOpenActivities,
  toast,
}: ChatSuggestionChipsProps) {
  const { dateFlexSuggestion, dateFlex, tripStartDate, tripEndDate } = useDocumentStore(
    useShallow((s) => ({
      dateFlexSuggestion: s.dateFlexSuggestion,
      dateFlex: s.document?.trip_inputs?.date_flex,
      tripStartDate: s.document?.trip_inputs?.start_date,
      tripEndDate: s.document?.trip_inputs?.end_date,
    }))
  );
  const showFlex = dateFlexSuggestion && !isLoading && !dateFlex;

  if (effectiveSuggestions.length === 0 && !showFlex) return null;
  if (isLoading) return null;

  const chips: SuggestionChip[] = suggestionChips.length > 0
    ? suggestionChips
    : effectiveSuggestions.map((text, i) => ({
        message: text,
        action_type: 'send_message' as const,
        action_target: null,
        chip_type: suggestedResponseMeta[i]?.chip_type || 'follow_up',
        category: suggestedResponseMeta[i]?.category || '',
        icon: suggestedResponseMeta[i]?.icon || null,
      }));

  return (
    <div
      key={`suggestions-container-${effectiveSuggestions.length}`}
      className="flex gap-2 overflow-x-auto overscroll-x-contain px-2 pb-1 pt-3 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
    >
      {showFlex && (
        <DateFlexChip
          flex={dateFlexSuggestion}
          onSendMessage={(msg, opts) => {
            useDocumentStore.getState().setDateFlexSuggestion(null);
            onSendMessage(msg, opts);
          }}
          tripStartDate={tripStartDate}
          tripEndDate={tripEndDate}
        />
      )}
      {chips.map((chip, idx) => (
        <SuggestionChipItem
          key={`sugg-${chip.message.slice(0, 20)}-${idx}`}
          chip={chip}
          idx={idx}
          resolvedAction={resolveChipAction(chip)}
          bookingTypes={bookingTypes}
          onUpdateFlightSettings={onUpdateFlightSettings}
          onUpdateBookingTypes={onUpdateBookingTypes}
          onConfirmReset={onConfirmReset}
          onOpenSheet={onOpenSheet}
          onSendMessage={onSendMessage}
          onOpenFlights={onOpenFlights}
          onOpenStays={onOpenStays}
          onOpenActivities={onOpenActivities}
          toast={toast}
        />
      ))}
    </div>
  );
}
