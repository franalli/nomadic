/**
 * Cross-trip booking preferences stored in localStorage.
 * These serve as defaults for new trips.
 */

import type {
  ActivitySettings,
  BookingTypes,
  FlightSettings,
  HotelSettings,
} from '@/types/document';

const PREFERENCES_STORAGE_KEY = 'nomadic_booking_prefs_v1';

export type BookingPreferences = {
  booking_types: BookingTypes;
  flight_settings: FlightSettings;
  hotel_settings: HotelSettings;
  activity_settings: ActivitySettings;
  updatedAt: string;
};

export const DEFAULT_BOOKING_TYPES: BookingTypes = {
  hotels: true,
  flights: true,
  activities: true,
};

export const DEFAULT_FLIGHT_SETTINGS: FlightSettings = {
  round_trip: true,
  cabin_class: 'economy',
  direct_only: false,
};

export const DEFAULT_HOTEL_SETTINGS: HotelSettings = {
  min_stars: 3,
  amenities: [],
};

export const DEFAULT_ACTIVITY_SETTINGS: ActivitySettings = {
  categories: [],
  max_duration_hours: null,
};

export const DEFAULT_BOOKING_PREFERENCES: BookingPreferences = {
  booking_types: DEFAULT_BOOKING_TYPES,
  flight_settings: DEFAULT_FLIGHT_SETTINGS,
  hotel_settings: DEFAULT_HOTEL_SETTINGS,
  activity_settings: DEFAULT_ACTIVITY_SETTINGS,
  updatedAt: new Date().toISOString(),
};

/**
 * Load booking preferences from localStorage.
 * Returns defaults if not found or invalid.
 */
export const loadBookingPreferences = (): BookingPreferences => {
  if (typeof window === 'undefined') return DEFAULT_BOOKING_PREFERENCES;
  try {
    const raw = window.localStorage.getItem(PREFERENCES_STORAGE_KEY);
    if (!raw) return DEFAULT_BOOKING_PREFERENCES;
    const parsed = JSON.parse(raw) as Partial<BookingPreferences>;
    // Merge with defaults to handle missing fields from older versions
    return {
      booking_types: { ...DEFAULT_BOOKING_TYPES, ...parsed.booking_types },
      flight_settings: { ...DEFAULT_FLIGHT_SETTINGS, ...parsed.flight_settings },
      hotel_settings: { ...DEFAULT_HOTEL_SETTINGS, ...parsed.hotel_settings },
      activity_settings: { ...DEFAULT_ACTIVITY_SETTINGS, ...parsed.activity_settings },
      updatedAt: parsed.updatedAt ?? new Date().toISOString(),
    };
  } catch (error) {
    console.warn('Failed to load booking preferences', error);
    return DEFAULT_BOOKING_PREFERENCES;
  }
};

/**
 * Save booking preferences to localStorage.
 */
export const saveBookingPreferences = (prefs: Partial<BookingPreferences>): void => {
  if (typeof window === 'undefined') return;
  try {
    const current = loadBookingPreferences();
    const updated: BookingPreferences = {
      ...current,
      ...prefs,
      updatedAt: new Date().toISOString(),
    };
    window.localStorage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(updated));
  } catch (error) {
    console.error('Failed to save booking preferences', error);
  }
};
