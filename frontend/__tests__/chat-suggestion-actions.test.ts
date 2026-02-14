import { describe, expect, it, vi } from 'vitest';

import { getSendBurstGuardReason, handleSuggestionTriggerAction } from '@/components/chat/ChatPanel';
import { DEFAULT_BOOKING_TYPES } from '@/state/documentStore';

describe('handleSuggestionTriggerAction', () => {
  it('applies one-tap direct flights action and flushes settings', () => {
    const onUpdateFlightSettings = vi.fn();
    const onUpdateBookingTypes = vi.fn();
    const ensureSettingsFlushed = vi.fn().mockResolvedValue(undefined);
    const toast = vi.fn();

    const handled = handleSuggestionTriggerAction({
      actionTarget: 'set_direct_flights_only',
      bookingTypes: { ...DEFAULT_BOOKING_TYPES, flights: 'off' },
      onUpdateFlightSettings,
      onUpdateBookingTypes,
      ensureSettingsFlushed,
      toast,
    });

    expect(handled).toBe(true);
    expect(onUpdateFlightSettings).toHaveBeenCalledWith({ direct_only: true });
    expect(onUpdateBookingTypes).toHaveBeenCalledWith({ flights: 'on' });
    expect(ensureSettingsFlushed).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledWith('Direct flights only enabled');
  });

  it('returns false for unknown trigger action', () => {
    const onUpdateFlightSettings = vi.fn();
    const onUpdateBookingTypes = vi.fn();
    const ensureSettingsFlushed = vi.fn().mockResolvedValue(undefined);
    const toast = vi.fn();

    const handled = handleSuggestionTriggerAction({
      actionTarget: 'unknown_action',
      bookingTypes: { ...DEFAULT_BOOKING_TYPES, flights: 'off' },
      onUpdateFlightSettings,
      onUpdateBookingTypes,
      ensureSettingsFlushed,
      toast,
    });

    expect(handled).toBe(false);
    expect(onUpdateFlightSettings).not.toHaveBeenCalled();
    expect(onUpdateBookingTypes).not.toHaveBeenCalled();
    expect(ensureSettingsFlushed).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });
});

describe('getSendBurstGuardReason', () => {
  it('rejects rapid repeated generate actions', () => {
    const reason = getSendBurstGuardReason({
      isGenerateTrigger: true,
      isLoading: false,
      now: 2_000,
      lastGenerateClickedAt: 0,
      lastMessageSentAt: 0,
    });
    expect(reason).toBe('Please wait a moment before generating again');
  });

  it('rejects rapid repeated normal messages', () => {
    const reason = getSendBurstGuardReason({
      isGenerateTrigger: false,
      isLoading: false,
      now: 1_500,
      lastGenerateClickedAt: 0,
      lastMessageSentAt: 800,
    });
    expect(reason).toBe("You're sending too quickly");
  });
});
