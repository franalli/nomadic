import { render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { DayCard } from '@/types/plan-envelope';

const { orchestrationState } = vi.hoisted(() => ({
  orchestrationState: {
    displayLogic: {
      isShowingMirrorLoader: false,
      tripDuration: 3,
      density: 'empty',
    },
    specialistData: {
      fullModeSections: [],
    },
    fullModePOIs: [],
    effectiveTiles: {},
    effectiveTripInputs: undefined,
    hasSectionData: false,
    hasItineraryContent: false,
    isStreaming: false,
    isAnyRegenerating: false,
    isRegenUpdating: false,
    isDesktop: true,
    preferenceCount: 0,
    effectiveMode: 'planning',
    timelineSectionRef: { current: null },
    scrollContainerRef: { current: null },
    handleSaveTile: vi.fn(),
    handleOpenBookingDrawer: vi.fn(),
    generating: false,
    effectiveDayCards: [] as DayCard[],
    nextAction: null,
    hideNextStepBar: false,
    shouldShowAutoProgress: false,
    progressStage: 'success',
    isCollapsed: false,
    bookingDrawerCategory: null,
    bookingDrawerPinnedDay: null,
    handleCloseBookingDrawer: vi.fn(),
  },
}));

vi.mock('@/components/plan/booking/BookingDrawer', () => ({
  BookingDrawer: () => null,
}));

vi.mock('@/components/plan/BookingSection', () => ({
  BookingSection: () => null,
}));

vi.mock('@/components/plan/ItineraryProgressIndicator', () => ({
  ItineraryProgressIndicator: () => null,
}));

vi.mock('@/components/plan/NextStepBar', () => ({
  NextStepBar: () => null,
}));

vi.mock('@/components/plan/PlanDensityViews', () => ({
  PlanMirrorLoader: () => createElement('div', { 'data-testid': 'mirror-loader' }),
}));

vi.mock('@/components/plan/PlanFullDensityView', () => ({
  PlanFullDensityView: () => createElement('div', { 'data-testid': 'full-density-view' }),
}));

vi.mock('@/components/plan/PlanHeader', () => ({
  PlanHeader: () => null,
}));

vi.mock('@/components/plan/useStrategyStageOrchestration', () => ({
  useStrategyStageOrchestration: () => orchestrationState,
  computeDataDensity: vi.fn(),
}));

import {
  shouldUsePlanMirrorLoader,
  StrategyStageRenderer,
} from '@/components/plan/StrategyStageRenderer';

describe('StrategyStageRenderer render path', () => {
  it('renders the full-density view once partial day cards exist', () => {
    orchestrationState.displayLogic = {
      isShowingMirrorLoader: true,
      tripDuration: 3,
      density: 'ghost',
    };
    orchestrationState.hasItineraryContent = true;
    orchestrationState.effectiveDayCards = [
      {
        day_number: 1,
        label: 'Day 1',
        blocks: [],
      },
    ];

    render(
      createElement(StrategyStageRenderer, {
        state: 'S2_STRATEGY_READY',
        viewModel: {
          strategy_sections: [],
          day_cards: [],
        },
      })
    );

    expect(screen.getByTestId('full-density-view')).toBeInTheDocument();
    expect(screen.queryByTestId('mirror-loader')).not.toBeInTheDocument();
  });
});

describe('shouldUsePlanMirrorLoader', () => {
  it('shows the mirror loader for normal ghost density', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'ghost',
        isPlanGenerationActive: false,
        hasPartialItinerary: false,
      })
    ).toBe(true);
  });

  it('shows the mirror loader while itinerary generation is active even if density is empty', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'empty',
        isPlanGenerationActive: true,
        hasPartialItinerary: false,
      })
    ).toBe(true);
  });

  it('shows the mirror loader while any plan generation is active even if density is bridge', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'bridge',
        isPlanGenerationActive: true,
        hasPartialItinerary: false,
      })
    ).toBe(true);
  });

  it('does not force the mirror loader when itinerary generation is inactive and density is empty', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'empty',
        isPlanGenerationActive: false,
        hasPartialItinerary: false,
      })
    ).toBe(false);
  });

  it('does not force the mirror loader once partial day cards exist', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: true,
        density: 'ghost',
        isPlanGenerationActive: true,
        hasPartialItinerary: true,
      })
    ).toBe(false);
  });

  it('keeps skeleton when tiles arrive during generation but no day_cards yet', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'ghost',
        isPlanGenerationActive: true,
        hasPartialItinerary: false,
        hasTiles: true,
      })
    ).toBe(true);
  });

  it('exits skeleton when tiles and day_cards both present during generation', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'ghost',
        isPlanGenerationActive: true,
        hasPartialItinerary: true,
        hasTiles: true,
      })
    ).toBe(false);
  });

  it('does not exit the mirror loader for tiles when generation is inactive', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'ghost',
        isPlanGenerationActive: false,
        hasPartialItinerary: false,
        hasTiles: true,
      })
    ).toBe(true);
  });

  it('keeps the mirror loader when no tiles and generation is active', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'ghost',
        isPlanGenerationActive: true,
        hasPartialItinerary: false,
        hasTiles: false,
      })
    ).toBe(true);
  });

  it('dismisses skeleton when generation ends even if no day_cards yet', () => {
    expect(
      shouldUsePlanMirrorLoader({
        isShowingMirrorLoader: false,
        density: 'full',
        isPlanGenerationActive: false,
        hasPartialItinerary: false,
        hasTiles: true,
      })
    ).toBe(false);
  });
});
