/**
 * Formatting utilities for TripSummaryPills
 *
 * These functions are specifically designed for the pill display in the header.
 * They may have different semantics than similar functions elsewhere (e.g., plan-transform.ts).
 */

/**
 * Parse a date string (ISO format yyyy-MM-dd) into a Date object.
 * Returns null if invalid.
 *
 * IMPORTANT: Uses manual parsing to avoid timezone issues.
 * new Date("2026-01-31") interprets as UTC midnight, which in local time
 * can appear as the previous day. We parse components directly to create
 * a local midnight date.
 */
function parseDate(dateStr: string | null | undefined): Date | null {
  if (!dateStr) return null;

  // Parse ISO date format (yyyy-MM-dd) as local time
  const parts = dateStr.split('-');
  if (parts.length === 3) {
    const year = parseInt(parts[0], 10);
    const month = parseInt(parts[1], 10);
    const day = parseInt(parts[2], 10);
    if (!isNaN(year) && !isNaN(month) && !isNaN(day)) {
      return new Date(year, month - 1, day); // month is 0-indexed
    }
  }

  // Fallback for other formats
  const date = new Date(dateStr);
  return isNaN(date.getTime()) ? null : date;
}

/**
 * Format date range for pill display.
 * Returns null if EITHER date is missing (triggers "missing" tone).
 * This is stricter than plan-transform.ts formatDateRange which returns a value if only start is present.
 *
 * @example formatDateRangeForPills("2024-12-15", "2024-12-22") → "Dec 15 – 22"
 * @example formatDateRangeForPills("2024-12-28", "2025-01-05") → "Dec 28 – Jan 5"
 * @example formatDateRangeForPills(null, "2024-12-22") → null
 */
export function formatDateRangeForPills(
  startDate: string | null | undefined,
  endDate: string | null | undefined
): string | null {
  const start = parseDate(startDate);
  const end = parseDate(endDate);

  // Both dates required for pills display
  if (!start || !end) return null;

  const formatter = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  });

  // Check if same month for compact format
  if (start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear()) {
    // Same month: "Dec 15 – 22"
    const monthDay = formatter.format(start); // "Dec 15"
    const endDay = end.getDate().toString();
    return `${monthDay} – ${endDay}`;
  }

  // Different months: "Dec 28 – Jan 5"
  return `${formatter.format(start)} – ${formatter.format(end)}`;
}

/**
 * Format travelers count for pill display.
 * Always returns a user-friendly string (never null).
 *
 * @example formatTravelersForPills(1, 0) → "1 adult"
 * @example formatTravelersForPills(2, 0) → "2 adults"
 * @example formatTravelersForPills(2, 1) → "2 adults · 1 child"
 * @example formatTravelersForPills(null, null) → "1 adult"
 */
export function formatTravelersForPills(
  adults: number | null | undefined,
  children: number | null | undefined
): string {
  const a = adults ?? 1; // Default to 1 adult
  const c = children ?? 0;

  const adultText = a === 1 ? '1 adult' : `${a} adults`;
  if (c === 0) return adultText;

  const childText = c === 1 ? '1 child' : `${c} children`;
  return `${adultText} · ${childText}`;
}

/**
 * Format budget for pill display.
 * Returns null if budget is not set (triggers "optional" tone).
 * Guards against invalid currency codes.
 *
 * @example formatBudgetForPills(2000, "USD") → "$2,000"
 * @example formatBudgetForPills(1500, "EUR") → "€1,500"
 * @example formatBudgetForPills(null, "USD") → null
 * @example formatBudgetForPills(2000, "INVALID") → "2,000 INVALID"
 */
export function formatBudgetForPills(
  budget: number | null | undefined,
  currency: string | null | undefined
): string | null {
  if (budget == null) return null;
  const curr = currency ?? 'USD';
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: curr,
      maximumFractionDigits: 0,
    }).format(budget);
  } catch {
    // Fallback for invalid currency codes
    return `${budget.toLocaleString('en-US')} ${curr}`;
  }
}
