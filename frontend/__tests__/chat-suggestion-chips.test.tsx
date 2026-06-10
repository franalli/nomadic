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

  it('opens activities sheet for an LLM CTA tagged with a bare "activities" category', () => {
    // Exact shape the suggestions LLM emits for "Add specific activities":
    // send_message + bare category 'activities'. Must open the activities
    // surface, not fire a vague text message (regression for dead green CTA).
    const { onOpenActivities, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Add specific activities',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'cta',
          category: 'activities',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Add specific activities'],
    });

    fireEvent.click(screen.getByRole('button', { name: /add specific activities/i }));

    expect(onOpenActivities).toHaveBeenCalledTimes(1);
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('opens stays sheet for an LLM CTA tagged with a bare "stays" category', () => {
    const { onOpenStays, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Find hotels in Bali',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'cta',
          category: 'stays',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Find hotels in Bali'],
    });

    fireEvent.click(screen.getByRole('button', { name: /find hotels in bali/i }));

    expect(onOpenStays).toHaveBeenCalledTimes(1);
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('still sends as a message when the category is not a pill target', () => {
    // "Extend trip to 10 days" (category='') is a genuine instruction the agent
    // acts on — it must keep firing as a message, not open a sheet.
    const { onSendMessage, onOpenActivities, onOpenStays, onOpenSheet } = renderChips({
      suggestionChips: [
        {
          message: 'Extend trip to 10 days',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'follow_up',
          category: '',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Extend trip to 10 days'],
    });

    fireEvent.click(screen.getByRole('button', { name: /extend trip to 10 days/i }));

    expect(onSendMessage).toHaveBeenCalledWith('Extend trip to 10 days', {
      suggestionClicked: 'Extend trip to 10 days',
    });
    expect(onOpenActivities).not.toHaveBeenCalled();
    expect(onOpenStays).not.toHaveBeenCalled();
    expect(onOpenSheet).not.toHaveBeenCalled();
  });

  it('does NOT open the destination sheet for a must-do follow_up chip tagged category=destination', () => {
    // Regression: local-expert must-do chips carry category='destination' as a
    // semantic source tag on a follow_up chip. They must send_message, not reopen
    // the destination picker. (Bare-category->pill rescue is CTA-only.)
    const { onSendMessage, onOpenSheet } = renderChips({
      suggestionChips: [
        {
          message: 'Visit Tanah Lot',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'follow_up',
          category: 'destination',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Visit Tanah Lot'],
    });

    fireEvent.click(screen.getByRole('button', { name: /visit tanah lot/i }));

    expect(onSendMessage).toHaveBeenCalledWith('Visit Tanah Lot', {
      suggestionClicked: 'Visit Tanah Lot',
    });
    expect(onOpenSheet).not.toHaveBeenCalled();
  });

  it('opens the dates sheet for an explicit "Set dates" chip despite category=date_prompt', () => {
    // "Set dates" emits open_pill/dates with category=date_prompt; the date_prompt
    // override must NOT downgrade it to a dead send_message.
    const { onOpenSheet, onSendMessage } = renderChips({
      suggestionChips: [
        {
          message: 'Set dates',
          action_type: 'open_pill',
          action_target: 'dates',
          chip_type: 'cta',
          category: 'date_prompt',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Set dates'],
    });

    fireEvent.click(screen.getByRole('button', { name: /set dates/i }));

    expect(onOpenSheet).toHaveBeenCalledWith('dates');
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('still sends a date-range chip (send_message + date_prompt) so the agent extracts dates', () => {
    const { onSendMessage, onOpenSheet } = renderChips({
      suggestionChips: [
        {
          message: 'Jul 12 - Jul 18',
          action_type: 'send_message',
          action_target: null,
          chip_type: 'cta',
          category: 'date_prompt',
          icon: null,
        },
      ],
      effectiveSuggestions: ['Jul 12 - Jul 18'],
    });

    fireEvent.click(screen.getByRole('button', { name: /jul 12 - jul 18/i }));

    expect(onSendMessage).toHaveBeenCalledWith('Jul 12 - Jul 18', {
      suggestionClicked: 'Jul 12 - Jul 18',
    });
    expect(onOpenSheet).not.toHaveBeenCalled();
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
