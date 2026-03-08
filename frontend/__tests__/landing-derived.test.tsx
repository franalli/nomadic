import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  useLandingDerived,
  type UseLandingDerivedParams,
} from '@/components/layout/hooks/useLandingDerived';
import { DEFAULT_TRIP_INPUTS } from '@/state/documentStore';
import type { StrategySection } from '@/types/plan-envelope';

const LOCAL_EXPERT_SECTION: StrategySection = {
  id: 'local-expert',
  title: 'Local Expert',
  specialist_type: 'local_expert',
  principles: [],
  must_dos: [],
  optional_upgrades: [],
  logistics_notes: [],
  bullets: [],
};

function makeParams(
  overrides: Partial<UseLandingDerivedParams> = {}
): UseLandingDerivedParams {
  return {
    storeTripInputs: { ...DEFAULT_TRIP_INPUTS },
    docPlanState: undefined,
    docDestinationCard: undefined,
    docPlanViewState: undefined,
    docStrategySections: [],
    docTiles: {},
    docExecutedTopics: [],
    docPendingTopics: [],
    docDayCards: [],
    docGeneration: undefined,
    docOpenDecisions: [],
    docItineraryOverview: undefined,
    docItineraryAssumptions: undefined,
    docNeedsRefresh: false,
    docCanExpand: false,
    destinationImageUrl: null,
    isGenerating: false,
    hasEverHadPlan: false,
    userRequestedGeneration: false,
    uiGeneration: null,
    localPendingTopics: [],
    hasBranchesReady: false,
    ...overrides,
  };
}

describe('useLandingDerived plan view gate', () => {
  it('returns null planViewState when destination is set but dates are missing', () => {
    const { result } = renderHook(() =>
      useLandingDerived(
        makeParams({
          storeTripInputs: {
            ...DEFAULT_TRIP_INPUTS,
            destination: 'Rome',
          },
          docStrategySections: [LOCAL_EXPERT_SECTION],
          hasEverHadPlan: true,
          hasBranchesReady: true,
          userRequestedGeneration: true,
        })
      )
    );

    // planViewState is null when prerequisites not met (backend SSoT invariant)
    expect(result.current.planViewState).toBeNull();
    expect(result.current.planTabEnabled).toBe(false);
    expect(result.current.canGeneratePlan).toBe(false);
  });

  it('returns null planViewState and isFraming=true during active generation without backend state', () => {
    const { result } = renderHook(() =>
      useLandingDerived(
        makeParams({
          storeTripInputs: {
            ...DEFAULT_TRIP_INPUTS,
            destination: 'Rome',
            start_date: '2026-03-01',
            end_date: '2026-03-07',
          },
          isGenerating: true,
          userRequestedGeneration: true,
        })
      )
    );

    // planViewState is null — backend hasn't responded yet
    expect(result.current.planViewState).toBeNull();
    // isFraming is the separate UI loading signal
    expect(result.current.isFraming).toBe(true);
  });

  it('unlocks strategy state once destination and both dates are present', () => {
    const { result } = renderHook(() =>
      useLandingDerived(
        makeParams({
          storeTripInputs: {
            ...DEFAULT_TRIP_INPUTS,
            destination: 'Rome',
            start_date: '2026-03-01',
            end_date: '2026-03-07',
          },
          docPlanViewState: 'S2_STRATEGY_READY',
          docStrategySections: [LOCAL_EXPERT_SECTION],
          hasEverHadPlan: true,
          hasBranchesReady: true,
        })
      )
    );

    expect(result.current.planViewState).toBe('S2_STRATEGY_READY');
    expect(result.current.planTabEnabled).toBe(true);
    expect(result.current.canGeneratePlan).toBe(true);
  });
});
