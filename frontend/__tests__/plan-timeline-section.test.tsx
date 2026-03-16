import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { PlanTimelineSection } from '../components/plan/PlanTimelineSection';

const { removeBlock, toast } = vi.hoisted(() => ({
  removeBlock: vi.fn(),
  toast: vi.fn(),
}));

vi.mock('@/components/ui/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/components/ui/toast', () => ({
  useToast: () => ({ toast }),
}));

vi.mock('@/state/documentStore', () => {
  const useDocumentStore = Object.assign(
    (selector: (state: { removeBlock: typeof removeBlock }) => unknown) =>
      selector({ removeBlock }),
    {
      getState: () => ({ undoEntry: null }),
    }
  );

  return { useDocumentStore };
});

vi.mock('../components/plan/timeline/DraggableBlock', () => ({
  DraggableBlock: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('../components/plan/timeline/DroppableDay', () => ({
  DroppableDay: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('../components/plan/timeline/FreeDayDropSlot', () => ({
  FreeDayDropSlot: () => <div data-testid="free-day-drop-slot" />,
}));

vi.mock('../components/plan/timeline/ItineraryDndWrapper', () => ({
  ItineraryDndWrapper: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('../components/plan/timeline/TimelineSkeleton', () => ({
  TimelineSkeleton: () => <div data-testid="timeline-skeleton">Preview-aware timeline skeleton</div>,
}));

vi.mock('../components/plan/TimelineThread', () => ({
  TimelineThread: ({ dayCards }: { dayCards: Array<{ day_number: number }> }) => (
    <div data-testid="timeline-thread">
      {dayCards.map((card) => `Day ${card.day_number}`).join(', ')}
    </div>
  ),
}));

describe('PlanTimelineSection loading states', () => {
  it('renders the preview-aware timeline skeleton while expanding without day cards', () => {
    render(
      <PlanTimelineSection
        dayCards={[]}
        timelineVariant="real"
        isStreaming
        isRegenUpdating={false}
        isExpandingItinerary
        hasItineraryContent={false}
        preferenceCount={0}
        savedTileIds={new Set()}
        timelineSectionRef={{ current: null }}
        handleOpenBookingDrawer={vi.fn()}
      />
    );

    expect(screen.getByTestId('timeline-skeleton')).toBeInTheDocument();
    expect(screen.getByText('Preview-aware timeline skeleton')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(
      'Building your itinerary. Specialist preview available.'
    );
    expect(screen.queryByTestId('timeline-thread')).not.toBeInTheDocument();
  });

  it('keeps the real timeline visible and adds a loading overlay during expand rebuilds', () => {
    render(
      <PlanTimelineSection
        dayCards={[
          {
            day_number: 1,
            label: 'Day 1',
            blocks: [],
          },
        ]}
        timelineVariant="real"
        isStreaming
        isRegenUpdating={false}
        isExpandingItinerary
        hasItineraryContent
        preferenceCount={0}
        savedTileIds={new Set()}
        timelineSectionRef={{ current: null }}
        handleOpenBookingDrawer={vi.fn()}
      />
    );

    expect(screen.getByTestId('timeline-thread')).toBeInTheDocument();
    expect(screen.getByText('Day 1')).toBeInTheDocument();
    expect(screen.getByText('Building your itinerary...')).toBeInTheDocument();
    expect(screen.queryByTestId('timeline-skeleton')).not.toBeInTheDocument();
  });

  it('keeps the Stage 3 loading skeleton visible when day cards clear before expand starts', () => {
    render(
      <PlanTimelineSection
        dayCards={[]}
        timelineVariant="real"
        isStreaming
        isRegenUpdating={false}
        isExpandingItinerary={false}
        hasItineraryContent
        preferenceCount={0}
        savedTileIds={new Set()}
        timelineSectionRef={{ current: null }}
        handleOpenBookingDrawer={vi.fn()}
      />
    );

    expect(screen.getByTestId('timeline-skeleton')).toBeInTheDocument();
    expect(screen.queryByTestId('timeline-thread')).not.toBeInTheDocument();
  });
});
