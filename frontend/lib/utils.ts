import { format } from 'date-fns';

export function cn(...inputs: Array<string | false | null | undefined>) {
  return inputs.filter(Boolean).join(' ');
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile Type Detection Utilities
// ─────────────────────────────────────────────────────────────────────────────

const FLIGHT_TYPE_KEYWORDS = ['flight', 'air', 'fare', 'plane'] as const;
const ACTIVITY_TYPE_KEYWORDS = ['activity', 'experience', 'tour', 'excursion', 'ticket', 'event'] as const;

/**
 * Check if a tile type string represents a flight.
 */
export const isFlightType = (type: string): boolean => {
  const lower = type.toLowerCase();
  return FLIGHT_TYPE_KEYWORDS.some((keyword) => lower.includes(keyword));
};

/**
 * Check if a tile type string represents an activity.
 */
export const isActivityType = (type: string): boolean => {
  const lower = type.toLowerCase();
  return ACTIVITY_TYPE_KEYWORDS.some((keyword) => lower.includes(keyword));
};

// ─────────────────────────────────────────────────────────────────────────────
// Date Formatting Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Format an ISO date string (YYYY-MM-DD) for display.
 * Returns a human-readable format like "Wed, Dec 15".
 */
export const formatDateForDisplay = (value?: string | null): string => {
  if (!value) return '';
  const isoMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (isoMatch) {
    try {
      const date = new Date(value + 'T00:00:00');
      return format(date, 'MMM d');
    } catch {
      return value;
    }
  }
  return value;
};

// ─────────────────────────────────────────────────────────────────────────────
// Budget Formatting Utilities
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parse a budget value to a number. Returns null if invalid or non-positive.
 */
export const parseBudgetNumber = (budget?: string | number | null): number | null => {
  if (budget === null || budget === undefined) return null;
  const text = typeof budget === 'number' ? budget.toString() : budget;
  const cleaned = text.replace(/[$,\s]/g, '');
  const parsed = parseFloat(cleaned);
  if (!Number.isFinite(parsed) || parsed <= 0) return null;
  return Math.round(parsed);
};

/**
 * Normalize a budget input to a trimmed string or null.
 */
export const normalizeBudgetInput = (budget?: string | number | null): string | null => {
  if (budget === null || budget === undefined) return null;
  const text = typeof budget === 'number' ? budget.toString() : budget;
  const trimmed = text.trim();
  return trimmed || null;
};

/**
 * Format a budget value for display (e.g., "$3,000").
 * Returns the numeric formatted value if parseable, otherwise the normalized string.
 */
export const formatBudgetDisplay = (budget?: string | number | null): string | null => {
  const numeric = parseBudgetNumber(budget);
  if (numeric) return `$${numeric.toLocaleString()}`;
  return normalizeBudgetInput(budget);
};

/**
 * Format a budget value for form display. Returns empty string if null/undefined.
 * Always returns a string (never null).
 */
export const formatBudgetValue = (value?: string | number | null): string => {
  if (value === null || value === undefined) return '';
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return '';
  return `$${Math.round(parsed).toLocaleString()}`;
};
