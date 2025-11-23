import type { TripSummaryPayload } from '@/types/summary';

export const SUMMARY_STORAGE_KEY = 'nomadic_trip_summary';

export const saveTripSummary = (payload: TripSummaryPayload): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(SUMMARY_STORAGE_KEY, JSON.stringify(payload));
  } catch (error) {
    console.error('Failed to cache trip summary', error);
  }
};

export const loadTripSummary = (): TripSummaryPayload | null => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(SUMMARY_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TripSummaryPayload;
    if (!parsed.selection?.activities) {
      parsed.selection = {
        ...parsed.selection,
        activities: [],
      };
    }
    return parsed;
  } catch (error) {
    console.error('Failed to load trip summary', error);
    return null;
  }
};

export const clearTripSummary = (): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(SUMMARY_STORAGE_KEY);
  } catch (error) {
    console.error('Failed to clear trip summary', error);
  }
};
