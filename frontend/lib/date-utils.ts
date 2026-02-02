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

/**
 * Format a Date object to ISO date string (yyyy-MM-dd) using local date components.
 * Avoids timezone issues with toISOString() which uses UTC.
 *
 * @example formatDateToISO(new Date(2026, 0, 31)) → "2026-01-31"
 */
export function formatDateToISO(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Add days to an ISO date string, returning a new ISO date string.
 * Uses UTC internally to avoid daylight saving issues.
 *
 * @example addDaysToISODate("2026-01-31", 1) → "2026-02-01"
 */
export function addDaysToISODate(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  const dateUTC = new Date(Date.UTC(y, m - 1, d));
  dateUTC.setUTCDate(dateUTC.getUTCDate() + days);
  return dateUTC.toISOString().slice(0, 10);
}

/**
 * Get day of week name from a Date object.
 *
 * @example getDayOfWeek(new Date(2026, 0, 31)) → "Saturday"
 */
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

export function getDayOfWeek(date: Date): string {
  return DAY_NAMES[date.getDay()];
}

/**
 * Add days to a Date object, returning a new Date.
 *
 * @example addDays(new Date(2026, 0, 31), 1) → Date for Feb 1, 2026
 */
export function addDays(date: Date, days: number): Date {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}
