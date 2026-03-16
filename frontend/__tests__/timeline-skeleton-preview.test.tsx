import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TimelineSkeleton } from '@/components/plan/timeline/TimelineSkeleton';

const { storeState } = vi.hoisted(() => ({
  storeState: {
    document: {
      strategy_sections: [] as Array<Record<string, unknown>>,
    },
  },
}));

vi.mock('@/state/documentStore', () => ({
  useDocumentStore: (
    selector: (state: {
      document: {
        strategy_sections: Array<Record<string, unknown>>;
      };
    }) => unknown
  ) => selector(storeState),
}));

describe('TimelineSkeleton preview', () => {
  beforeEach(() => {
    storeState.document.strategy_sections = [];
  });

  it('renders specialist preview titles from streamed strategy sections', () => {
    storeState.document.strategy_sections = [
      {
        specialist_type: 'diving',
        feasibility_status: 'feasible',
        content_added: [
          {
            title: 'USAT Liberty wreck dive',
            description: 'Morning shore entry with calmer conditions.',
          },
        ],
      },
    ];

    render(<TimelineSkeleton />);

    expect(screen.getAllByText('diving')).toHaveLength(2);
    expect(screen.getByText('USAT Liberty wreck dive')).toBeInTheDocument();
    expect(
      screen.getByText('Morning shore entry with calmer conditions.')
    ).toBeInTheDocument();
    expect(
      screen.getByText('Loading live availability around specialist picks')
    ).toBeInTheDocument();
  });

  it('falls back to generic loading copy when no preview data is available', () => {
    render(<TimelineSkeleton />);

    expect(screen.getByText('Creating your personalized itinerary')).toBeInTheDocument();
    expect(screen.queryByText('Specialist preview')).not.toBeInTheDocument();
  });
});
