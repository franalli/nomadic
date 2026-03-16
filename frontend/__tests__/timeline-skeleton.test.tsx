import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TimelineSkeleton } from '@/components/plan/timeline/TimelineSkeleton';

const mockUseDocumentStore = vi.fn();

vi.mock('@/state/documentStore', () => ({
  useDocumentStore: (selector: (state: {
    document: { strategy_sections: unknown[] } | null;
    _specialistPreview?: Array<Record<string, unknown>> | null;
  }) => unknown) =>
    selector(mockUseDocumentStore()),
}));

describe('TimelineSkeleton', () => {
  it('shows specialist preview content from the dedicated preview store field', () => {
    mockUseDocumentStore.mockReturnValue({
      _specialistPreview: [
        {
          title: 'USAT Liberty Shipwreck Shore Dive',
          description: 'Easy-entry wreck dive with strong marine life.',
          specialist_type: 'diving',
          duration_hours: 3,
        },
      ],
      document: {
        strategy_sections: [],
      },
    });

    render(<TimelineSkeleton />);

    expect(screen.getByText('USAT Liberty Shipwreck Shore Dive')).toBeInTheDocument();
    expect(screen.getByText('3h · diving')).toBeInTheDocument();
    expect(screen.getByText('Specialist preview')).toBeInTheDocument();
    expect(
      screen.getByText('Loading live availability around specialist picks')
    ).toBeInTheDocument();
  });

  it('falls back to generic shimmer copy when no specialist preview exists', () => {
    mockUseDocumentStore.mockReturnValue({
      _specialistPreview: null,
      document: {
        strategy_sections: [],
      },
    });

    render(<TimelineSkeleton />);

    expect(screen.getByText('Creating your personalized itinerary')).toBeInTheDocument();
    expect(screen.queryByText('Specialist preview')).not.toBeInTheDocument();
  });
});
