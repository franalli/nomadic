import { describe, expect, it } from 'vitest';

import { detectTopicsFromMessage } from '@/components/layout/LandingHelpers';

describe('detectTopicsFromMessage', () => {
  it('normalizes sailing keywords to the canonical sailing topic', () => {
    expect(detectTopicsFromMessage('Can you add a yacht day and some kayak options?')).toEqual([
      'sailing',
    ]);
  });
});
