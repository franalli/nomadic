import { describe, expect, it } from 'vitest';

import { FILL_DAY_COOLDOWN_MS, isFillDayCooldownActive } from '@/lib/fillDayGuards';

describe('isFillDayCooldownActive', () => {
  it('returns true within cooldown window', () => {
    const now = 2_000;
    const last = now - (FILL_DAY_COOLDOWN_MS - 1);
    expect(isFillDayCooldownActive(now, last)).toBe(true);
  });

  it('returns false outside cooldown window', () => {
    const now = 2_000;
    const last = now - (FILL_DAY_COOLDOWN_MS + 1);
    expect(isFillDayCooldownActive(now, last)).toBe(false);
  });
});
