import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/plan/modals/AlternativesModal', () => ({
  AlternativesModal: () => null,
}));

vi.mock('@/components/plan/tiles/SuggestionCard', () => ({
  SuggestionCard: ({ tile }: { tile: { title: string } }) => <div>{tile.title}</div>,
}));

vi.mock('@/components/tiles/TileDetailsModal', () => ({
  TileDetailsModal: () => null,
}));

import { LandingHeaderContent } from '@/components/layout/LandingHeaderContent';
import { BookingPlanningView } from '@/components/plan/BookingPlanningView';
import { TripSummaryPills } from '@/components/plan/TripSummaryPills';
import { usePanelToggleStore } from '@/state/panelToggleStore';
import type { DocumentTripInputs } from '@/types/document';
import type { Tile } from '@/types/tile';

function buildTile(id: string, type: Tile['type'], title: string): Tile {
  return {
    id,
    type,
    title,
    currency: 'USD',
  } as Tile;
}

const tripInputs: DocumentTripInputs = {
  destination: 'Lisbon',
  origin: 'Amsterdam',
  start_date: '2026-04-10',
  end_date: '2026-04-15',
  adults: 2,
  children: 0,
  budget: null,
  currency: 'USD',
  missing_fields: [],
  activity_settings: {
    categories: [],
  },
};

describe('BookingPlanningView activity panel routing', () => {
  beforeEach(() => {
    act(() => {
      usePanelToggleStore.getState().reset();
    });
  });

  afterEach(() => {
    act(() => {
      usePanelToggleStore.getState().reset();
    });
  });

  it('keeps activities hidden when only stays are open and shows them from the activities toggle', () => {
    const stayTile = buildTile('stay_1', 'hotel', 'Canal House');
    const activityTile = buildTile('activity_1', 'activity', 'Sunset Sail');

    const { unmount } = render(
      <BookingPlanningView
        filteredStayTiles={[stayTile]}
        filteredFlightTiles={[]}
        filteredActivityTiles={[activityTile]}
        tileArray={[stayTile, activityTile]}
        savedTileIds={new Set()}
        isExpanded
        flightsExpanded={false}
        hasDates
        effectiveMode="planning"
      />
    );

    expect(screen.getByText('Stays')).toBeInTheDocument();
    expect(screen.getByText('Canal House')).toBeInTheDocument();
    expect(screen.queryByText('Activities')).not.toBeInTheDocument();
    expect(screen.queryByText('Sunset Sail')).not.toBeInTheDocument();

    unmount();

    act(() => {
      usePanelToggleStore.getState().toggleActivities();
    });

    render(
      <BookingPlanningView
        filteredStayTiles={[stayTile]}
        filteredFlightTiles={[]}
        filteredActivityTiles={[activityTile]}
        tileArray={[stayTile, activityTile]}
        savedTileIds={new Set()}
        isExpanded={false}
        flightsExpanded={false}
        hasDates
        effectiveMode="planning"
      />
    );

    expect(screen.queryByText('Stays')).not.toBeInTheDocument();
    expect(screen.queryByText('Canal House')).not.toBeInTheDocument();
    expect(screen.getByText('Activities')).toBeInTheDocument();
    expect(screen.getByText('Sunset Sail')).toBeInTheDocument();
  });

  it('keeps panel toggles mutually exclusive when activities open', () => {
    act(() => {
      usePanelToggleStore.getState().toggleStays();
    });
    expect(usePanelToggleStore.getState()).toMatchObject({
      staysExpanded: true,
      activitiesExpanded: false,
    });

    act(() => {
      usePanelToggleStore.getState().toggleActivities();
    });

    expect(usePanelToggleStore.getState()).toMatchObject({
      staysExpanded: false,
      flightsExpanded: false,
      activitiesExpanded: true,
      intelExpanded: false,
    });
  });
});

describe('TripSummaryPills activities sheet trigger', () => {
  it('opens the activities sheet from the activities pill', () => {
    const onOpenSheet = vi.fn();

    render(
      <TripSummaryPills
        compact
        tripInputs={tripInputs}
        onOpenSheet={onOpenSheet}
      />
    );

    const activitiesButton = screen.getByRole('button', { name: 'Activities' });

    fireEvent.click(activitiesButton);

    expect(activitiesButton).not.toHaveAttribute('aria-pressed');
    expect(onOpenSheet).toHaveBeenCalledTimes(1);
    expect(onOpenSheet).toHaveBeenCalledWith('activities');
  });
});

describe('LandingHeaderContent activities sheet trigger', () => {
  beforeEach(() => {
    act(() => {
      usePanelToggleStore.getState().reset();
    });
  });

  afterEach(() => {
    act(() => {
      usePanelToggleStore.getState().reset();
    });
  });

  it('routes the header activities pill to the activities sheet instead of the panel toggle store', () => {
    const onOpenSheet = vi.fn();
    const headerTiles = {
      flight_1: buildTile('flight_1', 'flight', 'Flight to Lisbon'),
      stay_1: buildTile('stay_1', 'hotel', 'Lisbon Stay'),
    };

    render(
      <LandingHeaderContent
        tiles={headerTiles}
        tripInputs={tripInputs}
        dayCards={[]}
        openSheet={onOpenSheet}
        isGenerating={false}
        hasItineraryContent
        showHeaderPills
        user={null}
        otherTrips={[]}
        resumingTripId={null}
        userLoading={false}
        handleNewTrip={vi.fn(async () => {})}
        handleLogin={vi.fn(async () => {})}
        handleLogout={vi.fn(async () => {})}
        handleStartNewSession={vi.fn()}
        resumeTrip={vi.fn(async () => false)}
        addToast={vi.fn()}
        isResettingSession={false}
      />
    );

    const activitiesButton = screen.getByRole('button', { name: 'Activities' });
    const flightsButton = screen.getByRole('button', { name: /Flights/ });

    fireEvent.click(activitiesButton);

    expect(activitiesButton).not.toHaveAttribute('aria-pressed');
    expect(flightsButton).toHaveAttribute('aria-pressed', 'false');
    expect(usePanelToggleStore.getState().activitiesExpanded).toBe(false);
    expect(onOpenSheet).toHaveBeenCalledTimes(1);
    expect(onOpenSheet).toHaveBeenCalledWith('activities');
  });
});
