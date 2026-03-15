import { describe, expect, it } from 'vitest';

import { canonicalCategoryKey } from '@/lib/categoryNormalization';

describe('canonicalCategoryKey religious-site normalization', () => {
  it('maps exact religious-site categories to temples', () => {
    expect(canonicalCategoryKey('church')).toBe('temples');
    expect(canonicalCategoryKey('mosque')).toBe('temples');
    expect(canonicalCategoryKey('synagogue')).toBe('temples');
  });

  it('maps compound religious-site categories to temples', () => {
    expect(canonicalCategoryKey('historic_church')).toBe('temples');
    expect(canonicalCategoryKey('grand_mosque')).toBe('temples');
    expect(canonicalCategoryKey('place_of_worship')).toBe('temples');
  });
});
