export const FILL_DAY_COOLDOWN_MS = 1500;

export function isFillDayCooldownActive(now: number, lastRequestAt: number): boolean {
  return now - lastRequestAt < FILL_DAY_COOLDOWN_MS;
}
