/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * DatesSheet build-gate tests (LandingPrimarySheets).
 *
 * Regression: setting dates via the Dates sheet at S2 never fired the itinerary
 * build because the gate read the prerequisite-gated `planViewState` PROP (null
 * while dates are still missing) instead of the live store value. The fix reads
 * plan_view_state FRESH from the store inside onSave and routes through
 * guardedGeneratePlan, while skipping the fire when the multi-specialist
 * auto-trigger (useItineraryGenerationController) will handle the build instead.
 */

import { render, screen } from '@testing-library/react';
import { beforeEach,describe, expect, it, vi } from 'vitest';

import { LandingPrimarySheets } from '@/components/layout/LandingPrimarySheets';
import type { DocumentTripInputs } from '@/types/document';

// ---------------------------------------------------------------------------
// Store mocks — onSave reads fresh state from the document store at invocation.
// ---------------------------------------------------------------------------

const docState: {
  document: {
    plan_view_state?: string;
    trip_inputs?: { start_date?: string | null; end_date?: string | null };
    executed_strategy_topics?: string[];
    day_cards?: unknown[];
  };
} = { document: {} };

const addMessage = vi.fn();

vi.mock('@/state/documentStore', () => ({
  useDocumentStore: { getState: () => ({ document: docState.document }) },
}));

vi.mock('@/state/chatStore', () => ({
  GENERATE_PLAN_TRIGGER: 'GENERATE_PLAN_NOW',
  useChatStore: { getState: () => ({ addMessage }) },
}));

// ---------------------------------------------------------------------------
// Sheet stubs — render inert except DatesSheet, which exposes a button that
// invokes onSave with a fixed range when clicked.
// ---------------------------------------------------------------------------

const TEST_START = new Date(2026, 6, 1); // 2026-07-01 (local)
const TEST_END = new Date(2026, 6, 5); // 2026-07-05 (local)

vi.mock('@/components/plan/sheets/DatesSheet', () => ({
  DatesSheet: ({ onSave }: { onSave: (s: Date, e: Date) => void }) => (
    <button type="button" data-testid="dates-save" onClick={() => onSave(TEST_START, TEST_END)}>
      save
    </button>
  ),
}));

vi.mock('@/components/plan/sheets/DestinationSheet', () => ({
  DestinationSheet: () => null,
}));
vi.mock('@/components/plan/sheets/OriginSheet', () => ({ OriginSheet: () => null }));
vi.mock('@/components/plan/sheets/TravelersSheet', () => ({ TravelersSheet: () => null }));
vi.mock('@/components/plan/sheets/BudgetSheet', () => ({ BudgetSheet: () => null }));

// ---------------------------------------------------------------------------

const COMMITTED_DATES = { start_date: '2026-07-01', end_date: '2026-07-05' };

function renderSheets(overrides: Partial<Parameters<typeof LandingPrimarySheets>[0]> = {}) {
  const onSendMessage = vi.fn();
  const storeUpdateTripInputs = vi.fn();
  // Expose the commit promise so tests can await the exact onSave continuation
  // point (where the build gate runs) instead of guessing microtask counts.
  const storeCommitTripInputs = vi.fn().mockResolvedValue(true);
  const commitSettled = () =>
    Promise.all(storeCommitTripInputs.mock.results.map((r) => r.value)).then(() =>
      // Two extra microtask flushes for the awaited continuation + gate body.
      Promise.resolve().then(() => Promise.resolve())
    );
  render(
    <LandingPrimarySheets
      tripInputs={{ missing_fields: [] } as DocumentTripInputs}
      // Mirrors reality: the prop is null/undefined while dates are still missing.
      planViewState={undefined}
      activeSheet="dates"
      closeSheet={vi.fn()}
      openSheet={vi.fn()}
      addToast={vi.fn()}
      storeUpdateTripInputs={storeUpdateTripInputs}
      storeCommitTripInputs={storeCommitTripInputs}
      onSendMessage={onSendMessage}
      {...overrides}
    />
  );
  return { onSendMessage, commitSettled };
}

beforeEach(() => {
  vi.clearAllMocks();
  docState.document = {};
});

describe('DatesSheet build gate', () => {
  it('fires GENERATE_PLAN_TRIGGER for a single-specialist trip (auto-trigger will NOT handle)', async () => {
    docState.document = {
      plan_view_state: 'S2_STRATEGY_READY',
      trip_inputs: { ...COMMITTED_DATES },
      executed_strategy_topics: ['hiking'], // < 2 → no auto-trigger
      day_cards: [],
    };
    const { onSendMessage } = renderSheets();

    screen.getByTestId('dates-save').click();
    // Allow the awaited commit + gate to resolve.
    await vi.waitFor(() => expect(onSendMessage).toHaveBeenCalledWith('GENERATE_PLAN_NOW'));
  });

  it('does NOT fire when multi-specialist auto-trigger will handle the build', async () => {
    docState.document = {
      plan_view_state: 'S2_STRATEGY_READY',
      trip_inputs: { ...COMMITTED_DATES },
      executed_strategy_topics: ['hiking', 'diving'], // >= 2 → auto-trigger handles it
      day_cards: [],
    };
    const { onSendMessage, commitSettled } = renderSheets();

    screen.getByTestId('dates-save').click();
    await commitSettled();
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('does NOT fire when the store plan_view_state is bootstrap/undefined', async () => {
    docState.document = {
      // No plan_view_state — provisional/bootstrap document.
      trip_inputs: { ...COMMITTED_DATES },
      executed_strategy_topics: [],
      day_cards: [],
    };
    const { onSendMessage, commitSettled } = renderSheets();

    screen.getByTestId('dates-save').click();
    await commitSettled();
    expect(onSendMessage).not.toHaveBeenCalled();
  });
});
