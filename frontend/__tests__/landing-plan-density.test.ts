import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/layout/hooks/useBranchManager', () => ({
  useBranchManager: () => ({
    selectedBranchId: null,
    isGenerating: false,
    isRegenerating: false,
    readyToGenerate: false,
    hasBranchesReady: false,
    handleStartNewSession: vi.fn(),
    handlePlanResult: vi.fn(),
    handleGeneratePlanStart: vi.fn(),
    isHydratingSnapshot: false,
  }),
}));

vi.mock('@/components/layout/hooks/useItineraryGeneration', () => ({
  useItineraryGeneration: () => ({
    requestAutoExpandItinerary: vi.fn(),
    handleExpandToItinerary: vi.fn(),
    handleSelectNights: vi.fn(),
    hasItineraryContent: false,
  }),
}));

vi.mock('@/components/layout/hooks/useLandingDerived', () => ({
  useLandingDerived: vi.fn(),
}));

vi.mock('@/components/layout/hooks/useLandingEffects', () => ({
  useLandingEffects: () => ({
    tripInputsEditorRef: { current: null },
    finalizeTimerRef: { current: null },
  }),
}));

vi.mock('@/components/layout/hooks/useLandingHandlers', () => ({
  useLandingHandlers: () => ({
    handleStartNewSession: vi.fn(),
    handleSaveTilePreference: vi.fn(),
    handleOpenGearActivities: vi.fn(),
    handleOpenGearStays: vi.fn(),
    handleOpenGearFlights: vi.fn(),
    handleGeneratePlanStartWithSnapshot: vi.fn(),
    handlePlanResultWithReceipt: vi.fn(),
    handleUserMessageSubmit: vi.fn(),
    handleBuildPlan: vi.fn(),
    handleFinalizePlan: vi.fn(),
    handleMobileSend: vi.fn(),
    handleMobileStopStreaming: vi.fn(),
    handleSendMessage: vi.fn(),
    isResettingSession: false,
    isFinalizing: false,
    gearActivitiesSheetOpen: false,
    gearStaysSheetOpen: false,
    gearFlightsSheetOpen: false,
    setGearActivitiesSheetOpen: vi.fn(),
    setGearStaysSheetOpen: vi.fn(),
    setGearFlightsSheetOpen: vi.fn(),
  }),
}));

vi.mock('@/components/layout/hooks/useLocalBookingSettings', () => ({
  useLocalBookingSettings: () => ({
    bookingTypes: undefined,
    flightSettings: undefined,
    hotelSettings: undefined,
    activitySettings: undefined,
    handleUpdateBookingTypes: vi.fn(),
    handleUpdateFlightSettings: vi.fn(),
    handleUpdateHotelSettings: vi.fn(),
    handleUpdateActivitySettings: vi.fn(),
  }),
}));

vi.mock('@/components/layout/hooks/useTripInputsEditor', () => ({
  useTripInputsEditor: () => ({
    resetDraft: vi.fn(),
  }),
}));

vi.mock('@/components/plan/StrategyStageRenderer', () => ({
  computeDataDensity: vi.fn(() => 'empty'),
}));

import { computeLayoutDataDensity } from '@/components/layout/hooks/useLandingPlanState';
import type { GenerationState } from '@/components/plan/planStateHelpers';
import type { StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

const EMPTY_TILES: Record<string, Tile> = {};
const EMPTY_SECTIONS: StrategySection[] = [];

describe('computeLayoutDataDensity', () => {
  it('forces ghost density during active generation without destination data', () => {
    const generation: GenerationState = {
      active: true,
      stage: 'structure',
      message: 'Extracting trip details',
    };

    expect(
      computeLayoutDataDensity({
        hasDestination: false,
        planViewState: null,
        strategySections: EMPTY_SECTIONS,
        tiles: EMPTY_TILES,
        hasDates: false,
        generation,
      })
    ).toBe('ghost');
  });

  it('forces ghost density during active itinerary generation before strategy sections hydrate', () => {
    const generation: GenerationState = {
      active: true,
      stage: 'itinerary',
      message: 'Building itinerary',
    };

    expect(
      computeLayoutDataDensity({
        hasDestination: true,
        planViewState: null,
        strategySections: EMPTY_SECTIONS,
        tiles: EMPTY_TILES,
        hasDates: true,
        generation,
      })
    ).toBe('ghost');
  });

  it('keeps the normal density rules when itinerary generation is inactive', () => {
    expect(
      computeLayoutDataDensity({
        hasDestination: true,
        planViewState: null,
        strategySections: EMPTY_SECTIONS,
        tiles: EMPTY_TILES,
        hasDates: true,
        generation: null,
      })
    ).toBe('empty');
  });
});
