/**
 * Plan transformation utilities
 * Types and constants for plan data structures
 */

import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Segment Types
// ─────────────────────────────────────────────────────────────────────────────

export type SegmentType = 'flight' | 'stay' | 'transfer' | 'activity' | 'free_time';

export interface Segment {
  type: SegmentType;
  title: string;
  primary: string; // Main info line: "AMS → LIS · 06:40–08:30"
  secondary?: string; // Duration/details: "2h 50m · Direct"
  tertiary?: string; // Price or note: "Estimated cost: €180"
  tile?: Tile; // Associated tile if any
  isUnresolved?: boolean; // True if segment cannot be resolved with current constraints
}

export interface DayData {
  dayNumber: number;
  dayOfWeek: string | null;
  date: Date | null;
  segments: Segment[];
  notes?: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Conflict Types
// ─────────────────────────────────────────────────────────────────────────────

export type ConflictType = 'budget' | 'dates' | 'route';

export interface Conflict {
  type: ConflictType;
  primary: string;
  secondary: string;
}

export interface DerivedPlanData {
  days: DayData[];
  totalEstimate: number | null;
  hasUnresolvedSegments: boolean;
  conflicts: Conflict[];
}

/**
 * Format budget for display
 */
export function formatBudget(amount: number | null | undefined, currency: string = 'EUR'): string | null {
  if (amount == null) return null;

  const symbol = currency === 'EUR' ? '€' : currency === 'GBP' ? '£' : '$';
  return `${symbol}${amount.toLocaleString()}`;
}
