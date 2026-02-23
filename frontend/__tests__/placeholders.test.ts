import { describe, expect, it } from 'vitest';

import { placeholderImageForTile } from '@/lib/placeholders';

const CULTURE_IMAGE_IDS = [
  'photo-1493976040374-85c8e12f0c0e',
  'photo-1518998053901-5348d3961a04',
  'photo-1552832230-c0197dd311b5',
  'photo-1504598318550-17eba1008a68',
];

const ACTIVITY_IMAGE_IDS = [
  'photo-1527631746610-bca00a040d60',
  'photo-1501555088652-021faa106b9b',
  'photo-1551632811-561732d1e306',
  'photo-1506905925346-21bda4d32df4',
];

describe('placeholderImageForTile', () => {
  it('uses culture pool for cultural activity categories', () => {
    const url = placeholderImageForTile({
      id: 'tile_roman_forum',
      type: 'activity',
      category: 'cultural',
      destination: 'Rome',
    });

    expect(CULTURE_IMAGE_IDS.some((id) => url.includes(id))).toBe(true);
  });

  it('falls back to generic activity pool for unknown activity categories', () => {
    const url = placeholderImageForTile({
      id: 'tile_unknown_activity',
      type: 'activity',
      category: 'unknown',
      destination: 'Rome',
    });

    expect(ACTIVITY_IMAGE_IDS.some((id) => url.includes(id))).toBe(true);
  });
});
