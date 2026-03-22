/**
 * NextStepBarHelpers — Extracted date display logic for NextStepBar.
 */

interface DateDisplayResult {
  range: string;
  days: number | null;
  incomplete: boolean;
  pastDates: boolean;
}

interface TripDateInputs {
  start_date: string | null;
  end_date: string | null;
  trip_duration: number | null;
}

/** Check if dates are in the past. */
export function checkPastDates(startDate: string | null): boolean {
  if (!startDate) return false;
  const today = new Date().toISOString().split('T')[0];
  return startDate < today;
}

/** Format date range for display (handles incomplete and single-day trips). */
export function formatDateDisplay(tripInputs: TripDateInputs): DateDisplayResult | null {
  if (!tripInputs.start_date) return null;

  const start = new Date(tripInputs.start_date);
  const startStr = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const isPastDates = checkPastDates(tripInputs.start_date);

  if (isPastDates) {
    const endStr = tripInputs.end_date
      ? new Date(tripInputs.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : null;
    return {
      range: endStr ? `${startStr} — ${endStr}` : startStr,
      days: null,
      incomplete: true,
      pastDates: true,
    };
  }

  if (tripInputs.end_date) {
    const end = new Date(tripInputs.end_date);
    const isSameDay = start.toDateString() === end.toDateString();
    const days = Math.ceil((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)) + 1;

    if (isSameDay) {
      return { range: startStr, days: 1, incomplete: true, pastDates: false };
    }

    const endStr = end.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    return { range: `${startStr} — ${endStr}`, days, incomplete: false, pastDates: false };
  }

  if (tripInputs.trip_duration) {
    return { range: startStr, days: tripInputs.trip_duration, incomplete: false, pastDates: false };
  }

  return { range: `${startStr} → ?`, days: null, incomplete: true, pastDates: false };
}
