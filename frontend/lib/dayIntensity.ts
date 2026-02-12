import type { DayBlock } from '@/types/plan-envelope';

export type DayIntensity = 'relaxed' | 'moderate' | 'packed';

export const INTENSITY_CONFIG: Record<
  DayIntensity,
  { label: string; icon: string; pillClass: string }
> = {
  relaxed: { label: 'Relaxed', icon: 'Leaf', pillClass: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300' },
  moderate: { label: 'Balanced', icon: 'Sun', pillClass: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
  packed: { label: 'Packed', icon: 'Zap', pillClass: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300' },
};

const DURATION_TEXT_MAP: Record<string, number> = {
  'half day': 4,
  'full day': 8,
};

function parseDurationHours(duration?: string): number {
  if (!duration) return 2;
  const lower = duration.toLowerCase();
  for (const [text, hours] of Object.entries(DURATION_TEXT_MAP)) {
    if (lower.includes(text)) return hours;
  }
  const match = duration.match(/(\d+\.?\d*)/);
  return match ? parseFloat(match[1]) : 2;
}

/**
 * Compute day intensity from blocks. Returns null for anchor days
 * (arrival/departure) and days with no real activities.
 */
export function getDayIntensity(blocks: DayBlock[]): DayIntensity | null {
  // Skip logistics anchor days
  const anchorTypes = ['arrival', 'departure', 'check-in', 'check-out'];
  const isAnchorDay = blocks.some(
    (b) =>
      anchorTypes.includes(b.activity_type) ||
      anchorTypes.includes(b.buffer_type ?? '')
  );
  if (isAnchorDay) return null;

  // Count real activity blocks (exclude buffers and free_day placeholders)
  const activityBlocks = blocks.filter(
    (b) => !b.is_buffer && b.activity_type !== 'free_day'
  );

  if (activityBlocks.length === 0) return null;

  const totalHours = activityBlocks.reduce(
    (sum, b) => sum + parseDurationHours(b.duration),
    0
  );

  const blockScore =
    activityBlocks.length >= 3 ? 3 : activityBlocks.length >= 2 ? 2 : 1;
  const hourScore = totalHours > 8 ? 3 : totalHours > 4 ? 2 : 1;

  const intensity = Math.max(blockScore, hourScore);
  return intensity >= 3 ? 'packed' : intensity >= 2 ? 'moderate' : 'relaxed';
}
