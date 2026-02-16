/**
 * Centralized date utilities to avoid timezone issues.
 *
 * IMPORTANT: These utilities parse ISO date strings (yyyy-MM-dd) as local midnight
 * to avoid timezone shift issues. Using `new Date("2026-01-31")` directly
 * interprets the date as UTC midnight, which in local time can appear as
 * the previous day.
 */

/**
 * Parse an ISO date string (yyyy-MM-dd) into a Date object at local midnight.
 * Returns null if invalid.
 *
 * @example parseISODateLocal("2026-01-31") → Date at local midnight Jan 31
 * @example parseISODateLocal(null) → null
 */
export function parseISODateLocal(dateStr: string | null | undefined): Date | null {
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

  // Fallback for other formats (but may have timezone issues)
  const date = new Date(dateStr);
  return isNaN(date.getTime()) ? null : date;
}
