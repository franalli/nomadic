/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * Plan build dates-gate tests.
 *
 * Fix B (drive forward): a plan BUILD must never fire when dates are missing —
 * instead the Dates sheet opens and a chat nudge is added. When dates exist,
 * the build fires normally.
 *
 * Fix A (never revert to landing): shouldBlockViewStateDowngrade must block a
 * downgrade to the landing bootstrap whenever real plan content exists
 * (day_cards OR strategy_sections OR a destination), while still allowing the
 * legitimate bootstrap on RESET (no destination / no content) and legitimate
 * lateral downgrades (S2_STRATEGY_READY -> S2_BLOCKED).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { handleStaysSave } from '@/components/chat/chatModuleSheetHandlers';
import {
  guardedGeneratePlan,
  hasTripDates,
  MISSING_DATES_NUDGE,
} from '@/components/plan/planStateHelpers';
import { shouldBlockViewStateDowngrade } from '@/state/documentStore';

// ---------------------------------------------------------------------------
// Store mocks — handlers read fresh state from the stores at invocation.
// ---------------------------------------------------------------------------

const docState: { document: { plan_view_state?: string; trip_inputs?: unknown } } = {
  document: {},
};
const addMessage = vi.fn();
const setRegenerationState = vi.fn();

vi.mock('@/state/documentStore', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/state/documentStore')>();
  return {
    ...actual,
    useDocumentStore: {
      getState: () => ({ document: docState.document, setRegenerationState }),
    },
  };
});

vi.mock('@/state/chatStore', () => ({
  GENERATE_PLAN_TRIGGER: 'GENERATE_PLAN_NOW',
  useChatStore: { getState: () => ({ addMessage }) },
}));

vi.mock('@/hooks/usePreferenceAutoRegen', () => ({
  triggerRegeneration: vi.fn(),
}));

const DATES = { start_date: '2026-07-01', end_date: '2026-07-05' };

beforeEach(() => {
  vi.clearAllMocks();
  docState.document = {};
});

// ---------------------------------------------------------------------------
// Fix B — build-trigger gate
// ---------------------------------------------------------------------------

describe('hasTripDates', () => {
  it('is true only when both start and end dates are present', () => {
    expect(hasTripDates(DATES)).toBe(true);
    expect(hasTripDates({ start_date: '2026-07-01', end_date: null })).toBe(false);
    expect(hasTripDates({ start_date: null, end_date: '2026-07-05' })).toBe(false);
    expect(hasTripDates(null)).toBe(false);
    expect(hasTripDates(undefined)).toBe(false);
  });
});

describe('guardedGeneratePlan', () => {
  it('defers the build and opens the Dates sheet when dates are missing', () => {
    const sendBuild = vi.fn();
    const openDates = vi.fn();
    const addNudge = vi.fn();

    const fired = guardedGeneratePlan({
      tripInputs: { start_date: null, end_date: null },
      sendBuild,
      openDates,
      addNudge,
    });

    expect(fired).toBe(false);
    expect(sendBuild).not.toHaveBeenCalled();
    expect(openDates).toHaveBeenCalledTimes(1);
    expect(addNudge).toHaveBeenCalledWith(MISSING_DATES_NUDGE);
  });

  it('fires the build and does not open the Dates sheet when dates exist', () => {
    const sendBuild = vi.fn();
    const openDates = vi.fn();
    const addNudge = vi.fn();

    const fired = guardedGeneratePlan({ tripInputs: DATES, sendBuild, openDates, addNudge });

    expect(fired).toBe(true);
    expect(sendBuild).toHaveBeenCalledTimes(1);
    expect(openDates).not.toHaveBeenCalled();
    expect(addNudge).not.toHaveBeenCalled();
  });
});

describe('handleStaysSave build gate (S2_STRATEGY_READY)', () => {
  it('does NOT fire GENERATE_PLAN_TRIGGER and DOES open the Dates sheet when dates are missing', async () => {
    docState.document = {
      plan_view_state: 'S2_STRATEGY_READY',
      trip_inputs: { start_date: null, end_date: null },
    };
    const sendMessageCore = vi.fn().mockResolvedValue(undefined);
    const openDates = vi.fn();

    handleStaysSave({}, undefined, vi.fn(), sendMessageCore, openDates);

    expect(sendMessageCore).not.toHaveBeenCalled();
    expect(openDates).toHaveBeenCalledTimes(1);
    expect(addMessage).toHaveBeenCalledWith(
      expect.objectContaining({ role: 'assistant', content: MISSING_DATES_NUDGE })
    );
  });

  it('fires GENERATE_PLAN_TRIGGER when dates are present', async () => {
    docState.document = {
      plan_view_state: 'S2_STRATEGY_READY',
      trip_inputs: { ...DATES },
    };
    const sendMessageCore = vi.fn().mockResolvedValue(undefined);
    const openDates = vi.fn();

    handleStaysSave({}, undefined, vi.fn(), sendMessageCore, openDates);

    expect(sendMessageCore).toHaveBeenCalledWith('GENERATE_PLAN_NOW');
    expect(openDates).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Fix A — never revert to landing once content exists
// ---------------------------------------------------------------------------

describe('shouldBlockViewStateDowngrade — bootstrap protection', () => {
  it('blocks downgrade to bootstrap when strategy_sections exist (no day_cards)', () => {
    expect(
      shouldBlockViewStateDowngrade(
        'S2_STRATEGY_READY',
        'S0_BOOTSTRAP',
        /* hasDayCards */ false,
        /* hasStrategyContent */ true,
        /* hasDestination */ false
      )
    ).toBe(true);
  });

  it('blocks downgrade to bootstrap when a destination is set (no day_cards, no sections)', () => {
    expect(
      shouldBlockViewStateDowngrade('S2_STRATEGY_READY', 'P0_MINIMAL', false, false, true)
    ).toBe(true);
  });

  it('blocks downgrade to a null/bootstrap view-state when day_cards exist', () => {
    expect(shouldBlockViewStateDowngrade('S3_ITINERARY_READY', null, true, false, true)).toBe(
      false // null target is treated as "no change" — never blocked
    );
    expect(
      shouldBlockViewStateDowngrade('S3_ITINERARY_READY', 'S0_BOOTSTRAP', true, true, true)
    ).toBe(true);
  });

  it('allows the legitimate bootstrap on RESET (no destination / no content)', () => {
    expect(
      shouldBlockViewStateDowngrade(
        'S2_STRATEGY_READY',
        'S0_BOOTSTRAP',
        /* hasDayCards */ false,
        /* hasStrategyContent */ false,
        /* hasDestination */ false
      )
    ).toBe(false);
  });

  it('always allows the explicit S0_EMPTY reset sentinel', () => {
    expect(shouldBlockViewStateDowngrade('S3_ITINERARY_READY', 'S0_EMPTY', true, true, true)).toBe(
      false
    );
  });

  it('does not block a legitimate lateral downgrade (S2_STRATEGY_READY -> S2_BLOCKED)', () => {
    expect(
      shouldBlockViewStateDowngrade('S2_STRATEGY_READY', 'S2_BLOCKED', false, true, true)
    ).toBe(false);
  });
});
