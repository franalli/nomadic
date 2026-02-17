/**
 * Suggestion chip action handlers — shared between ChatPanel and ChatSuggestionChips.
 * Extracted to avoid circular imports.
 */

import type { BookingTypes, FlightSettings } from '@/types/document';

export type SuggestionTriggerActionParams = {
  actionTarget?: string | null;
  bookingTypes?: BookingTypes;
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  ensureSettingsFlushed?: (options?: { requestId?: string; sendCycleId?: string }) => Promise<void>;
  toast?: (message: string) => void;
};

export function handleSuggestionTriggerAction(params: SuggestionTriggerActionParams): boolean {
  const {
    actionTarget,
    bookingTypes,
    onUpdateFlightSettings,
    onUpdateBookingTypes,
    ensureSettingsFlushed,
    toast,
  } = params;

  if (actionTarget !== 'set_direct_flights_only') {
    return false;
  }

  onUpdateFlightSettings?.({ direct_only: true });
  if (bookingTypes?.flights === 'off') {
    onUpdateBookingTypes?.({ flights: 'on' });
  }
  void ensureSettingsFlushed?.();
  toast?.('Direct flights only enabled');
  return true;
}
