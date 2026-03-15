import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LogisticsBlock } from '@/components/plan/timeline/blocks/LogisticsBlock';

describe('LogisticsBlock sizing', () => {
  it('renders check-in thumbnails in the shared 48px container', () => {
    render(
      <LogisticsBlock
        type="checkin"
        hotelName="Canal House"
        hotelImage="https://images.example.com/canal-house.jpg"
      />
    );

    const image = screen.getByRole('img', { name: 'Canal House' });
    const container = image.parentElement;

    expect(container).toHaveClass('h-12', 'w-12');
    expect(image).toHaveClass('h-full', 'w-full', 'object-cover');
  });

  it('renders arrival logos inside the same 48px container with a larger contained logo', () => {
    render(
      <LogisticsBlock
        type="arrival"
        hotelImage="https://images.example.com/emirates-logo.png"
        deeplinkLabel="Book on Aviasales"
        deeplinkUrl="https://www.aviasales.com/search"
      />
    );

    const image = screen.getByRole('img', { name: 'Arrival' });
    const container = image.parentElement;

    expect(container).toHaveClass('h-12', 'w-12');
    expect(image).toHaveClass('h-8', 'w-8', 'object-contain');
  });
});
