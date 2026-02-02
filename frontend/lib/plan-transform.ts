/**
 * Plan transformation utilities
 * Derives day-by-day structure from branch flow and tiles
 */

import type { DocumentTripInputs } from '@/types/document';
import type { Tile } from '@/types/tile';

import {
  addDays,
  getDayOfWeek,
  parseISODateLocal as parseDate,
} from './date-utils';

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
// Segment Parsing
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Infer segment type from description text
 */
function inferSegmentType(description: string): SegmentType {
  const lower = description.toLowerCase();

  if (lower.includes('flight') || lower.includes('fly') || lower.includes('→') && lower.includes('airport')) {
    return 'flight';
  }
  if (lower.includes('hotel') || lower.includes('stay') || lower.includes('check in') || lower.includes('check-in') || lower.includes('accommodation')) {
    return 'stay';
  }
  if (lower.includes('transfer') || lower.includes('taxi') || lower.includes('train') || lower.includes('bus') || lower.includes('drive')) {
    return 'transfer';
  }
  if (lower.includes('free') || lower.includes('leisure') || lower.includes('relax') || lower.includes('explore on your own')) {
    return 'free_time';
  }

  return 'activity';
}

/**
 * Parse a flow description into segments
 * Flow items are typically day descriptions like:
 * "Arrive in Lisbon, check into hotel, explore Alfama district"
 */
function parseSegmentsFromDescription(description: string, tiles: Tile[]): Segment[] {
  // Split by common separators
  const parts = description.split(/[,;]/).map(p => p.trim()).filter(Boolean);

  if (parts.length === 0) {
    return [{
      type: 'free_time',
      title: 'Free time',
      primary: description || 'No activities planned',
    }];
  }

  return parts.map(part => {
    const type = inferSegmentType(part);

    // Try to find a matching tile
    const matchingTile = tiles.find(tile =>
      part.toLowerCase().includes(tile.title.toLowerCase()) ||
      tile.title.toLowerCase().includes(part.toLowerCase().slice(0, 20))
    );

    return {
      type,
      title: formatSegmentTitle(type),
      primary: part,
      secondary: matchingTile?.subtitle,
      tertiary: matchingTile?.price_estimate
        ? `Estimated cost: ${matchingTile.currency === 'EUR' ? '€' : '$'}${matchingTile.price_estimate}`
        : undefined,
      tile: matchingTile,
    };
  });
}

function formatSegmentTitle(type: SegmentType): string {
  switch (type) {
    case 'flight': return 'Flight';
    case 'stay': return 'Accommodation';
    case 'transfer': return 'Transfer';
    case 'activity': return 'Activity';
    case 'free_time': return 'Free time';
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Transformation
// ─────────────────────────────────────────────────────────────────────────────

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
 * Detect conflicts between constraints and plan
 */
function detectConflicts(
  tripInputs: DocumentTripInputs,
  totalEstimate: number | null,
  days: DayData[]
): Conflict[] {
  const conflicts: Conflict[] = [];

  // Budget conflict: estimate exceeds budget
  if (tripInputs.budget != null && totalEstimate != null && totalEstimate > tripInputs.budget) {
    conflicts.push(CONFLICT_COPY.budget);
  }

  // Dates conflict: flow has more days than date range allows
  if (tripInputs.start_date && tripInputs.end_date && days.length > 0) {
    const start = parseDate(tripInputs.start_date);
    const end = parseDate(tripInputs.end_date);
    if (start && end) {
      const rangeDays = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;
      if (days.length > rangeDays) {
        conflicts.push(CONFLICT_COPY.dates);
      }
    }
  }

  return conflicts;
}

/**
 * Transform branch flow and tiles into a day-by-day plan structure
 */
export function deriveDaysFromFlow(
  flow: string[] | undefined,
  tiles: Tile[],
  tripInputs: DocumentTripInputs
): DerivedPlanData {
  if (!flow?.length) {
    return {
      days: [],
      totalEstimate: null,
      hasUnresolvedSegments: false,
      conflicts: [],
    };
  }

  const startDate = parseDate(tripInputs.start_date);
  let totalEstimate = 0;
  let hasEstimates = false;
  let hasUnresolvedSegments = false;

  const days: DayData[] = flow.map((description, idx) => {
    const date = startDate ? addDays(startDate, idx) : null;
    const segments = parseSegmentsFromDescription(description, tiles);

    // Sum up estimates
    for (const segment of segments) {
      if (segment.tile?.price_estimate) {
        totalEstimate += segment.tile.price_estimate;
        hasEstimates = true;
      }
      if (segment.isUnresolved) {
        hasUnresolvedSegments = true;
      }
    }

    return {
      dayNumber: idx + 1,
      dayOfWeek: date ? getDayOfWeek(date) : null,
      date,
      segments,
    };
  });

  const finalEstimate = hasEstimates ? totalEstimate : null;
  const conflicts = detectConflicts(tripInputs, finalEstimate, days);

  return {
    days,
    totalEstimate: finalEstimate,
    hasUnresolvedSegments,
    conflicts,
  };
}

/**
 * Format a date range for display
 */
export function formatDateRange(startDate: string | null | undefined, endDate: string | null | undefined): string | null {
  const start = parseDate(startDate);
  const end = parseDate(endDate);

  if (!start) return null;

  const formatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  });

  if (!end || start.getTime() === end.getTime()) {
    return formatter.format(start);
  }

  return `${formatter.format(start)} – ${formatter.format(end)}`;
}

/**
 * Format budget for display
 */
export function formatBudget(amount: number | null | undefined, currency: string = 'EUR'): string | null {
  if (amount == null) return null;

  const symbol = currency === 'EUR' ? '€' : currency === 'GBP' ? '£' : '$';
  return `${symbol}${amount.toLocaleString()}`;
}
