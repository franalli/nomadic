import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it, vi } from 'vitest';

import { routeLayerStyle } from '@/components/map/InteractiveMapHelpers';
import { getPinConfig } from '@/components/map/map-marker-config';
import { DS } from '@/lib/design-system';

vi.mock('mapbox-gl', () => ({
  default: {
    setTelemetryEnabled: vi.fn(),
  },
}));

describe('map marker config', () => {
  it.each([
    'hotel',
    'accommodation',
    'lodging',
    'stay',
    'check-in',
    'check-out',
    'check_in',
    'check_out',
  ])('uses the DS emerald token for %s markers', (type) => {
    expect(getPinConfig(type).color).toBe(DS.brand.emerald);
  });
});

describe('interactive map helpers', () => {
  it('uses the DS emerald token for route styling', () => {
    expect(routeLayerStyle.paint?.['line-color']).toBe(DS.brand.emerald);
  });

  it('declares the client boundary explicitly', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'components/map/InteractiveMapHelpers.tsx'),
      'utf8'
    );
    const firstLine = source.split(/\r?\n/, 1)[0]?.trim();

    expect(firstLine).toBe("'use client';");
  });
});
