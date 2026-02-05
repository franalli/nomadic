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
export type TimeSlot = 'MORNING' | 'AFTERNOON' | 'EVENING';

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

/**
 * Tailwind color mapping for specialist types (badge/text colors)
 */
export const TOPIC_COLORS: Record<string, string> = {
  diving: 'cyan',
  hiking: 'emerald',
  skiing: 'blue',
  cycling: 'lime',
  boating: 'indigo',
  local_expert: 'zinc',
  general: 'zinc',
};

/**
 * Hex color values for timeline block borders (multi-specialist visual distinction)
 * Used for 4px left-border color coding
 */
export const SPECIALIST_COLORS: Record<string, string> = {
  local_expert: '#6B7280', // Neutral gray - foundational content
  diving: '#0EA5E9',       // Ocean blue - aquatic activities
  hiking: '#10B981',       // Forest green - terrestrial activities
  skiing: '#3B82F6',       // Snow blue - alpine activities
  cycling: '#84CC16',      // Lime - cycling activities
  boating: '#6366F1',      // Indigo - water activities
  default: '#71717A',      // Zinc - fallback
};

/**
 * Get Tailwind color classes for a specialist type
 */
export function getTopicColor(specialistType?: string): string {
  return TOPIC_COLORS[specialistType || ''] || 'zinc';
}

/**
 * Get hex color for timeline block border
 */
export function getSpecialistBorderColor(specialistType?: string): string {
  return SPECIALIST_COLORS[specialistType || ''] || SPECIALIST_COLORS.default;
}
