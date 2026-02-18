/**
 * Shared types for timeline block components
 */

import type { DayBlock } from '@/types/plan-envelope';

/**
 * Time display mode - exact timestamp vs time slot badge
 */
export interface DisplayTime {
  type: 'exact' | 'slot';
  value: string; // "08:00 AM" or "MORNING"
}

/**
 * Time slot labels for fallback display
 */
type TimeSlot = 'MORNING' | 'AFTERNOON' | 'EVENING';

/**
 * Get display time for a block with graceful fallback
 *
 * Priority:
 * 1. Exact scheduled_time from backend → monospace "08:00 AM"
 * 2. Period field → badge pill "MORNING"
 * 3. Block index position → synthesize from order
 */
export function getDisplayTime(block: DayBlock, blockIndex: number): DisplayTime {
  // Priority 1: Exact scheduled time from backend (format ISO to readable)
  if (block.scheduled_time) {
    const date = new Date(block.scheduled_time);
    const formatted = date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
    return { type: 'exact', value: formatted };
  }

  // Priority 2: Use period field if available
  if (block.period) {
    return { type: 'slot', value: block.period.toUpperCase() };
  }

  // Priority 3: Synthesize from block position
  const slots: TimeSlot[] = ['MORNING', 'AFTERNOON', 'EVENING'];
  const slot = slots[Math.min(blockIndex, slots.length - 1)];
  return { type: 'slot', value: slot };
}
