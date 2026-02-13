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

export const CONFLICT_COPY: Record<ConflictType, Conflict> = {
  budget: {
    type: 'budget',
    primary: 'Budget is lower than estimated plan cost.',
    secondary: 'The plan will adjust if constraints change.',
  },
  dates: {
    type: 'dates',
    primary: 'Dates are too short for current travel constraints.',
    secondary: 'Adjust dates or origin to resolve.',
  },
  route: {
    type: 'route',
    primary: 'No viable route matches current constraints.',
    secondary: 'The plan will update if constraints change.',
  },
};

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
