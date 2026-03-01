'use client';

/**
 * ChatSuggestionBar — Suggestion chip row shown below the input.
 *
 * Thin orchestration wrapper around ChatSuggestionChips.
 * ChatPanel passes its sheet-open state setters here so the
 * bar can open flights/stays/activities sheets without those
 * setters leaking further up the tree.
 */

import type {
  BookingTypes,
  FlightSettings,
  SuggestionChip,
  SuggestionChipMeta,
} from '@/types/document';
import type { SheetType } from '@/types/sheets';

import { ChatSuggestionChips } from './ChatSuggestionChips';

interface ChatSuggestionBarProps {
  effectiveSuggestions: string[];
  suggestionChips: SuggestionChip[];
  suggestedResponseMeta: SuggestionChipMeta[];
  isLoading: boolean;
  bookingTypes?: BookingTypes;
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  onOpenSheet?: (sheet: SheetType) => void;
  onConfirmReset?: () => void;
  onSendMessage: (message: string, options?: { suggestionClicked?: string }) => void;
  onOpenFlights: () => void;
  onOpenStays: () => void;
  onOpenActivities: () => void;
  toast: (message: string) => void;
}

export function ChatSuggestionBar(props: ChatSuggestionBarProps) {
  return <ChatSuggestionChips {...props} />;
}
