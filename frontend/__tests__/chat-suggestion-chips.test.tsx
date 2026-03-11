import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ChatSuggestionChips } from '@/components/chat/ChatSuggestionChips';
import type { SuggestionChip } from '@/types/document';

type Overrides = {
  suggestionChips?: SuggestionChip[];
  effectiveSuggestions?: string[];
};

function renderChips(overrides: Overrides = {}) {
  const onOpenSheet = vi.fn();
  const onSendMessage = vi.fn();
  const onOpenFlights = vi.fn();
  const onOpenStays = vi.fn();
  const onOpenActivities = vi.fn();
  const onUpdateFlightSettings = vi.fn();
  const onUpdateBookingTypes = vi.fn();
  const toast = vi.fn();

  render(
    <ChatSuggestionChips
      effectiveSuggestions={overrides.effectiveSuggestions ?? ['Set my budget']}
      suggestionChips={overrides.suggestionChips ?? []}
      suggestedResponseMeta={[]}
      isLoading={false}
      onOpenSheet={onOpenSheet}
      onSendMessage={onSendMessage}
      onOpenFlights={onOpenFlights}
      onOpenStays={onOpenStays}
      onOpenActivities={onOpenActivities}
      onUpdateFlightSettings={onUpdateFlightSettings}
      onUpdateBookingTypes={onUpdateBookingTypes}
      toast={toast}
    />
  );

  return {
    onOpenSheet,
    onSendMessage,
    onOpenFlights,
    onOpenStays,
    onOpenActivities,
    onUpdateFlightSettings,
    onUpdateBookingTypes,
    toast,
  };
}

describe('ChatSuggestionChips fallback action routing', () => {
  it('opens budget sheet when chip category is plan_budget but action is send_message', () => {
    const { onOpenSheet, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Set my budget',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'setting',
          category: 'plan_budget',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Set my budget'],
    });

    fireEvent.click(screen.getByRole('button', { name: /set my budget/i }));

    expect(onOpenSheet).toHaveBeenCalledWith('budget');
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('opens activities sheet from message heuristic when category/action are missing', () => {
    const { onOpenActivities, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Browse activities in Rome',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'follow_up',
          category: '',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Browse activities in Rome'],
    });

    fireEvent.click(screen.getByRole('button', { name: /browse activities in rome/i }));

    expect(onOpenActivities).toHaveBeenCalledTimes(1);
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('normalizes non-canonical open_pill targets and opens the right sheet', () => {
    const { onOpenStays, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Compare hotel options',
          action_type: 'open_pill',
          action_target: 'hotels',
          chip_type: 'setting',
          category: 'plan_hotels_compare',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Compare hotel options'],
    });

    fireEvent.click(screen.getByRole('button', { name: /compare hotel options/i }));

    expect(onOpenStays).toHaveBeenCalledTimes(1);
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('falls back to category routing when explicit action target is invalid', () => {
    const { onOpenSheet, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Set my budget',
          action_type: 'open_pill',
          action_target: 'finance',
          chip_type: 'setting',
          category: 'plan_budget',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Set my budget'],
    });

    fireEvent.click(screen.getByRole('button', { name: /set my budget/i }));

    expect(onOpenSheet).toHaveBeenCalledWith('budget');
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('sends pre-plan date chips as chat messages even if metadata says open_pill', () => {
    const { onOpenSheet, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Feb 27-01',
          action_type: 'open_pill',
          action_target: 'dates',
          chip_type: 'cta',
          category: 'date_prompt',
          icon: 'calendar',
        },
      ],
      effectiveSuggestions: ['Feb 27-01'],
    });

    fireEvent.click(screen.getByRole('button', { name: /feb 27-01/i }));

    expect(onOpenSheet).not.toHaveBeenCalled();
    expect(onSendMessage).toHaveBeenCalledWith('Feb 27-01', {
      suggestionClicked: 'Feb 27-01',
    });
  });

  it('keeps suggestion chips in a horizontal reel without wrapping', () => {
    renderChips();

    const container = screen.getByRole('button', { name: /set my budget/i }).parentElement;

    expect(container?.className).toContain('overflow-x-auto');
    expect(container?.className).not.toContain('flex-wrap');
  });

  it('does not infer planning styling from message text alone', () => {
    renderChips({
      suggestionChips: [
        {
          message: 'Plan hotels',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'follow_up',
          category: '',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Plan hotels'],
    });

    const button = screen.getByRole('button', { name: /plan hotels/i });
    expect(button.className).not.toContain('bg-emerald-50');
  });

  it('uses structured metadata to style planning chips', () => {
    renderChips({
      suggestionChips: [
        {
          message: 'Direct flights only',
          action_type: 'trigger_action',
          action_target: 'set_direct_flights_only',
          chip_type: 'setting',
          category: 'plan_flight_direct',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Direct flights only'],
    });

    const button = screen.getByRole('button', { name: /direct flights only/i });
    expect(button.className).toContain('bg-emerald-50');
  });
});
