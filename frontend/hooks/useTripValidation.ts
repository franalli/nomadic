/**
 * useTripValidation
 *
 * Unified date validation hook with state-aware messaging.
 * Single source of truth for trip validation across components.
 *
 * @see docs/ux_unified_architecture.md
 */

import { useMemo } from 'react';

import { useDocumentStore } from '@/state/documentStore';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type ValidationReason =
  | 'no_destination'
  | 'no_dates'
  | 'no_return_date'
  | 'same_day'
  | 'too_short'
  | 'valid';

export interface TripValidation {
  /** Whether the trip can be generated */
  valid: boolean;
  /** Reason code for invalid state */
  reason: ValidationReason;
  /** Human-readable message for user feedback */
  message: string;
  /** Action button text when invalid */
  action: string;
  /** Trip duration in days (null if invalid) */
  duration: number | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Calculate days between two ISO date strings.
 * Returns the number of nights (end - start).
 */
function daysBetween(start: string, end: string): number {
  const startDate = new Date(start);
  const endDate = new Date(end);
  const diffMs = endDate.getTime() - startDate.getTime();
  return Math.ceil(diffMs / (1000 * 60 * 60 * 24));
}

// ─────────────────────────────────────────────────────────────────────────────
// Validation Logic
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Core validation function - can be used independently of React.
 */
export function validateTripDates(
  destination: string | null | undefined,
  startDate: string | null | undefined,
  endDate: string | null | undefined,
  dateFlex: boolean | undefined,
  tripDuration: number | null | undefined
): TripValidation {
  // Check destination first
  if (!destination) {
    return {
      valid: false,
      reason: 'no_destination',
      message: 'Add a destination to start planning',
      action: 'Add Destination',
      duration: null,
    };
  }

  // Flexible dates with duration is valid
  if (dateFlex === true && tripDuration != null && tripDuration >= 2) {
    return {
      valid: true,
      reason: 'valid',
      message: '',
      action: 'Build Itinerary',
      duration: tripDuration,
    };
  }

  // No start date
  if (!startDate) {
    return {
      valid: false,
      reason: 'no_dates',
      message: 'Add dates to build your itinerary',
      action: 'Add Dates',
      duration: null,
    };
  }

  // No end date
  if (!endDate) {
    return {
      valid: false,
      reason: 'no_return_date',
      message: 'Add a return date to continue',
      action: 'Add Return Date',
      duration: null,
    };
  }

  // Calculate duration
  const duration = daysBetween(startDate, endDate);

  // Same day trip
  if (duration === 0) {
    return {
      valid: false,
      reason: 'same_day',
      message: 'Trip must be at least 2 days',
      action: 'Adjust Dates',
      duration: 0,
    };
  }

  // Too short
  if (duration < 1) {
    return {
      valid: false,
      reason: 'too_short',
      message: 'Trip must be at least 2 days',
      action: 'Adjust Dates',
      duration,
    };
  }

  // Valid!
  return {
    valid: true,
    reason: 'valid',
    message: '',
    action: 'Build Itinerary',
    duration: duration + 1, // +1 to include both start and end day
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

/**
 * useTripValidation
 *
 * React hook for accessing trip validation state from the document store.
 * Provides state-aware messaging for UI components.
 *
 * @example
 * const { valid, message, action, duration } = useTripValidation();
 *
 * <Button disabled={!valid}>
 *   {valid ? 'Build Itinerary' : action}
 * </Button>
 * {!valid && <p className="text-sm text-muted-foreground">{message}</p>}
 */
export function useTripValidation(): TripValidation {
  const tripInputs = useDocumentStore((s) => s.document?.trip_inputs);

  return useMemo(
    () =>
      validateTripDates(
        tripInputs?.destination,
        tripInputs?.start_date,
        tripInputs?.end_date,
        tripInputs?.date_flex,
        tripInputs?.trip_duration
      ),
    [
      tripInputs?.destination,
      tripInputs?.start_date,
      tripInputs?.end_date,
      tripInputs?.date_flex,
      tripInputs?.trip_duration,
    ]
  );
}
