/* eslint no-unused-vars: ["error", { "args": "none" }] */
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';

import {
  areActivitiesDuplicate,
  deduplicateActivities,
  normalizeActivityWithEmoji,
} from '@/lib/utils';
import {
  DEFAULT_TRIP_INPUTS,
  markSettingDirty,
  useDocumentStore,
} from '@/state/documentStore';
import {
  type ActivitySettings,
  type BookingTypes,
  type BookingTypeState,
  type DocumentTripInputs,
  type DocumentTripInputsPatch,
  type FlightSettings,
  type HotelSettings,
  isBookingEnabled,
  type TransportSettings,
} from '@/types/document';
import type { ToastType } from '@/types/hooks';

/**
 * 8.1.2: Shallow object comparison for settings objects (avoids JSON.stringify on every render).
 * Returns true if objects are shallowly equal.
 */
function shallowSettingsEqual<T extends Record<string, unknown>>(
  a: T | null | undefined,
  b: T | null | undefined
): boolean {
  if (a === b) return true;
  if (!a || !b) return a === b;
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    const valA = a[key];
    const valB = b[key];
    // For arrays, compare by length and elements
    if (Array.isArray(valA) && Array.isArray(valB)) {
      if (valA.length !== valB.length) return false;
      for (let i = 0; i < valA.length; i++) {
        if (valA[i] !== valB[i]) return false;
      }
    } else if (valA !== valB) {
      return false;
    }
  }
  return true;
}

interface UseLocalBookingSettingsReturn {
  bookingTypes: BookingTypes;
  flightSettings: FlightSettings;
  hotelSettings: HotelSettings;
  transportSettings: TransportSettings;
  activitySettings: ActivitySettings;
  handleUpdateBookingTypes: (settings: Partial<BookingTypes>) => void;
  handleUpdateFlightSettings: (settings: Partial<FlightSettings>) => void;
  handleUpdateHotelSettings: (settings: Partial<HotelSettings>) => void;
  handleUpdateTransportSettings: (settings: Partial<TransportSettings>) => void;
  handleUpdateActivitySettings: (settings: Partial<ActivitySettings>) => void;
  handleAddActivity: (activity: string) => void;
  handleRemoveActivity: (index: number) => void;
}

// Debounce delay for batching rapid setting changes
const COMMIT_DEBOUNCE_MS = 300;

/**
 * Hook to manage local booking settings state.
 * Allows UI to work before document exists, syncs from store when available.
 *
 * Key design decisions:
 * - Local state is the source of truth for UI (allows optimistic updates)
 * - Refs track pending changes to prevent sync-back from overwriting user edits
 * - Debounced commits batch rapid changes to avoid race conditions with isCommitting lock
 * - Pre-document changes are queued and flushed when document becomes available
 */
export function useLocalBookingSettings(
  storeTripInputs: DocumentTripInputs | null | undefined,
  onToast: (message: string, type?: ToastType) => void
): UseLocalBookingSettingsReturn {
  // Single subscription: boolean + stable action refs (useShallow comparison is cheap)
  const { hasDocument, commitTripInputs, updateTripInputs } =
    useDocumentStore(useShallow((s) => ({
      hasDocument: !!s.document,
      commitTripInputs: s.commitTripInputs,
      updateTripInputs: s.updateTripInputs,
    })));

  // Local state for booking settings - initialize from store if available, else defaults
  const [localBookingTypes, setLocalBookingTypes] = useState<BookingTypes>(
    () => storeTripInputs?.booking_types ?? DEFAULT_TRIP_INPUTS.booking_types!
  );
  const [localFlightSettings, setLocalFlightSettings] = useState<FlightSettings>(
    () => storeTripInputs?.flight_settings ?? DEFAULT_TRIP_INPUTS.flight_settings!
  );
  const [localHotelSettings, setLocalHotelSettings] = useState<HotelSettings>(
    () => storeTripInputs?.hotel_settings ?? DEFAULT_TRIP_INPUTS.hotel_settings!
  );
  const [localTransportSettings, setLocalTransportSettings] = useState<TransportSettings>(
    () => storeTripInputs?.transport_settings ?? DEFAULT_TRIP_INPUTS.transport_settings!
  );
  const [localActivitySettings, setLocalActivitySettings] = useState<ActivitySettings>(
    () => storeTripInputs?.activity_settings ?? DEFAULT_TRIP_INPUTS.activity_settings!
  );

  // Refs to track latest settings values for use in callbacks
  const bookingTypesRef = useRef(localBookingTypes);
  const flightSettingsRef = useRef(localFlightSettings);
  const hotelSettingsRef = useRef(localHotelSettings);
  const transportSettingsRef = useRef(localTransportSettings);
  const activitySettingsRef = useRef(localActivitySettings);

  // Refs to track if we have pending local changes that shouldn't be overwritten by store sync
  const hasPendingBookingTypesChanges = useRef(false);
  const hasPendingFlightChanges = useRef(false);
  const hasPendingHotelChanges = useRef(false);
  const hasPendingTransportChanges = useRef(false);
  const hasPendingActivityChanges = useRef(false);

  // Debounce timers for each settings type
  const bookingTypesCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flightCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hotelCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transportCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activityCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Queue for pre-document changes - flushed when document becomes available
  const pendingCommitsQueue = useRef<DocumentTripInputsPatch | null>(null);

  // Keep refs in sync with state
  useEffect(() => { bookingTypesRef.current = localBookingTypes; }, [localBookingTypes]);
  useEffect(() => { flightSettingsRef.current = localFlightSettings; }, [localFlightSettings]);
  useEffect(() => { hotelSettingsRef.current = localHotelSettings; }, [localHotelSettings]);
  useEffect(() => { transportSettingsRef.current = localTransportSettings; }, [localTransportSettings]);
  useEffect(() => { activitySettingsRef.current = localActivitySettings; }, [localActivitySettings]);

  // 8.1.2: Refs to track previous store values for shallow comparison (avoids JSON.stringify on every render)
  const prevStoreBookingTypes = useRef(storeTripInputs?.booking_types);
  const prevStoreFlightSettings = useRef(storeTripInputs?.flight_settings);
  const prevStoreHotelSettings = useRef(storeTripInputs?.hotel_settings);
  const prevStoreTransportSettings = useRef(storeTripInputs?.transport_settings);
  const prevStoreActivitySettings = useRef(storeTripInputs?.activity_settings);

  // Sync local state from store when store values change (only if no pending local changes)
  // 8.1.2: Using shallow comparison instead of JSON.stringify for better performance
  // Also reset to defaults when storeTripInputs becomes null (e.g., on session reset)
  useEffect(() => {
    const storeVal = storeTripInputs?.booking_types;
    if (!hasPendingBookingTypesChanges.current) {
      if (!storeVal) {
        // Reset to defaults when store is cleared
        setLocalBookingTypes(DEFAULT_TRIP_INPUTS.booking_types!);
      } else if (!shallowSettingsEqual(storeVal, prevStoreBookingTypes.current)) {
        setLocalBookingTypes(storeVal);
      }
    }
    prevStoreBookingTypes.current = storeVal;
  }, [storeTripInputs?.booking_types]);

  useEffect(() => {
    const storeVal = storeTripInputs?.flight_settings;
    if (!hasPendingFlightChanges.current) {
      if (!storeVal) {
        setLocalFlightSettings(DEFAULT_TRIP_INPUTS.flight_settings!);
      } else if (!shallowSettingsEqual(storeVal, prevStoreFlightSettings.current)) {
        setLocalFlightSettings(storeVal);
      }
    }
    prevStoreFlightSettings.current = storeVal;
  }, [storeTripInputs?.flight_settings]);

  useEffect(() => {
    const storeVal = storeTripInputs?.hotel_settings;
    if (!hasPendingHotelChanges.current) {
      if (!storeVal) {
        setLocalHotelSettings(DEFAULT_TRIP_INPUTS.hotel_settings!);
      } else if (!shallowSettingsEqual(storeVal, prevStoreHotelSettings.current)) {
        setLocalHotelSettings(storeVal);
      }
    }
    prevStoreHotelSettings.current = storeVal;
  }, [storeTripInputs?.hotel_settings]);

  useEffect(() => {
    const storeVal = storeTripInputs?.transport_settings;
    if (!hasPendingTransportChanges.current) {
      if (!storeVal) {
        setLocalTransportSettings(DEFAULT_TRIP_INPUTS.transport_settings!);
      } else if (!shallowSettingsEqual(storeVal, prevStoreTransportSettings.current)) {
        setLocalTransportSettings(storeVal);
      }
    }
    prevStoreTransportSettings.current = storeVal;
  }, [storeTripInputs?.transport_settings]);

  useEffect(() => {
    const storeVal = storeTripInputs?.activity_settings;
    if (!hasPendingActivityChanges.current) {
      if (!storeVal) {
        setLocalActivitySettings(DEFAULT_TRIP_INPUTS.activity_settings!);
      } else if (!shallowSettingsEqual(storeVal, prevStoreActivitySettings.current)) {
        setLocalActivitySettings(storeVal);
      }
    }
    prevStoreActivitySettings.current = storeVal;
  }, [storeTripInputs?.activity_settings]);

  // Flush queued commits when document becomes available
  useEffect(() => {
    if (hasDocument && pendingCommitsQueue.current) {
      const queuedCommits = pendingCommitsQueue.current;
      pendingCommitsQueue.current = null;
      // Commit all queued changes in a single batched request
      commitTripInputs(queuedCommits)
        .then(() => {
          // Clear all pending flags after successful commit
          hasPendingBookingTypesChanges.current = false;
          hasPendingFlightChanges.current = false;
          hasPendingHotelChanges.current = false;
          hasPendingTransportChanges.current = false;
          hasPendingActivityChanges.current = false;
        })
        .catch((e) => {
          console.error('[useLocalBookingSettings] commitTripInputs failed:', e);
        });
    }
  }, [hasDocument, commitTripInputs]);

  // Clear pending flags and timers when store is reset (storeTripInputs becomes null)
  useEffect(() => {
    if (!storeTripInputs) {
      // Clear all pending flags so sync-back can reset local state
      hasPendingBookingTypesChanges.current = false;
      hasPendingFlightChanges.current = false;
      hasPendingHotelChanges.current = false;
      hasPendingTransportChanges.current = false;
      hasPendingActivityChanges.current = false;
      // Clear any pending commits queue
      pendingCommitsQueue.current = null;
      // Clear all debounce timers
      if (bookingTypesCommitTimer.current) {
        clearTimeout(bookingTypesCommitTimer.current);
        bookingTypesCommitTimer.current = null;
      }
      if (flightCommitTimer.current) {
        clearTimeout(flightCommitTimer.current);
        flightCommitTimer.current = null;
      }
      if (hotelCommitTimer.current) {
        clearTimeout(hotelCommitTimer.current);
        hotelCommitTimer.current = null;
      }
      if (transportCommitTimer.current) {
        clearTimeout(transportCommitTimer.current);
        transportCommitTimer.current = null;
      }
      if (activityCommitTimer.current) {
        clearTimeout(activityCommitTimer.current);
        activityCommitTimer.current = null;
      }
    }
  }, [storeTripInputs]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (bookingTypesCommitTimer.current) clearTimeout(bookingTypesCommitTimer.current);
      if (flightCommitTimer.current) clearTimeout(flightCommitTimer.current);
      if (hotelCommitTimer.current) clearTimeout(hotelCommitTimer.current);
      if (transportCommitTimer.current) clearTimeout(transportCommitTimer.current);
      if (activityCommitTimer.current) clearTimeout(activityCommitTimer.current);
    };
  }, []);

  // Origin-aware flights: Auto-suggest flights when origin is set
  // Tri-state invariant: Only upgrade 'off' -> 'suggested', never touch 'on' or existing 'suggested'
  // Guard: Also check store's booking_types — the atomic PATCH in LandingSheets/
  // useTripInputsEditor may have already upgraded flights to 'suggested' in the
  // same commit as origin. Without this check, bookingTypesRef (synced next render)
  // still reads 'off' and fires a harmless but wasteful duplicate commit.
  useEffect(() => {
    const hasOrigin = !!storeTripInputs?.origin;
    const currentFlightsState = bookingTypesRef.current.flights;
    const storeFlightsState = storeTripInputs?.booking_types?.flights;

    if (hasOrigin && currentFlightsState === 'off' && storeFlightsState === 'off') {
      const updated = { ...bookingTypesRef.current, flights: 'suggested' as BookingTypeState };
      bookingTypesRef.current = updated;
      setLocalBookingTypes(updated);

      // Commit the auto-suggestion (if document exists)
      if (hasDocument) {
        commitTripInputs({ booking_types: updated });
      } else {
        pendingCommitsQueue.current = {
          ...pendingCommitsQueue.current,
          booking_types: updated,
        };
      }
    }
  }, [
    storeTripInputs?.origin,
    storeTripInputs?.booking_types?.flights,
    hasDocument,
    commitTripInputs,
  ]);

  // Helper to commit settings with debounce and queue support
  const commitWithDebounce = useCallback(
    (
      updates: DocumentTripInputsPatch,
      timerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>,
      pendingRef: React.MutableRefObject<boolean>
    ) => {
      // Mark as having pending changes
      pendingRef.current = true;

      // Always sync to zustand immediately so ensureSettingsFlushed can
      // PATCH these to the backend before the graph starts (race fix).
      updateTripInputs(updates);

      // Clear existing timer
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      // If no document exists, queue the changes for later
      if (!hasDocument) {
        pendingCommitsQueue.current = {
          ...pendingCommitsQueue.current,
          ...updates,
        };
        return;
      }

      // Debounce the commit to batch rapid changes
      timerRef.current = setTimeout(async () => {
        const success = await commitTripInputs(updates);
        if (success) {
          pendingRef.current = false;
        }
        // If commit failed (e.g., isCommitting lock), the pending flag stays true
        // and sync-back won't overwrite local state
      }, COMMIT_DEBOUNCE_MS);
    },
    [hasDocument, commitTripInputs, updateTripInputs]
  );

  const ensureBookingTypeEnabled = useCallback(
    (key: keyof BookingTypes) => {
      // Tri-state: 'suggested' or 'on' are considered enabled
      if (isBookingEnabled(bookingTypesRef.current[key])) return bookingTypesRef.current;

      // When enabling via sub-settings, set to 'on' (user intent)
      const updated = { ...bookingTypesRef.current, [key]: 'on' as BookingTypeState };
      bookingTypesRef.current = updated;
      setLocalBookingTypes(updated);

      // Commit booking toggle immediately (debounced)
      commitWithDebounce(
        { booking_types: updated },
        bookingTypesCommitTimer,
        hasPendingBookingTypesChanges
      );

      return updated;
    },
    [commitWithDebounce]
  );

  // Booking types update handler
  const handleUpdateBookingTypes = useCallback(
    (settings: Partial<BookingTypes>) => {
      markSettingDirty('booking_types');
      const currentSettings = bookingTypesRef.current;
      const newSettings = { ...currentSettings, ...settings };
      // Update ref and state synchronously so rapid clicks work correctly
      bookingTypesRef.current = newSettings;
      setLocalBookingTypes(newSettings);

      // Commit with debounce (handles queue for pre-document state)
      commitWithDebounce(
        { booking_types: newSettings },
        bookingTypesCommitTimer,
        hasPendingBookingTypesChanges
      );

      // Generate confirmation toast based on what actually changed
      const typeLabels: Record<keyof BookingTypes, string> = {
        flights: 'flights',
        hotels: 'hotels',
        ground_transport: 'ground transport',
        activities: 'activities',
      };
      for (const [type, newValue] of Object.entries(settings) as [keyof BookingTypes, BookingTypeState][]) {
        if (type in typeLabels) {
          const oldValue = currentSettings[type];
          const wasEnabled = isBookingEnabled(oldValue);
          const isEnabled = isBookingEnabled(newValue);
          if (wasEnabled !== isEnabled) {
            const label = typeLabels[type];
            onToast(
              isEnabled ? `Added ${label} to search!` : `Removed ${label} from search.`,
              'confirmation'
            );
          }
        }
      }
    },
    [commitWithDebounce, onToast]
  );

  // Flight settings update handler
  const handleUpdateFlightSettings = useCallback(
    (settings: Partial<FlightSettings>) => {
      markSettingDirty('flight_settings');
      ensureBookingTypeEnabled('flights');
      const currentSettings = flightSettingsRef.current;
      const newSettings = { ...currentSettings, ...settings };
      // Update ref and state synchronously so rapid clicks work correctly
      flightSettingsRef.current = newSettings;
      setLocalFlightSettings(newSettings);

      // Commit with debounce (handles queue for pre-document state)
      commitWithDebounce(
        { flight_settings: newSettings },
        flightCommitTimer,
        hasPendingFlightChanges
      );

      // Generate assistant message based on what actually changed
      const messages: string[] = [];
      if ('round_trip' in settings && currentSettings.round_trip !== settings.round_trip) {
        messages.push(settings.round_trip ? 'round trip' : 'one way');
      }
      if ('direct_only' in settings && currentSettings.direct_only !== settings.direct_only) {
        messages.push(settings.direct_only ? 'direct flights only' : 'any stops');
      }
      if ('cabin_class' in settings && currentSettings.cabin_class !== settings.cabin_class) {
        const classLabels: Record<string, string> = {
          economy: 'economy',
          premium_economy: 'premium economy',
          business: 'business class',
          first: 'first class',
        };
        messages.push(classLabels[settings.cabin_class!] ?? settings.cabin_class!);
      }
      if (messages.length > 0) {
        onToast(`Updated flight settings: ${messages.join(', ')}! ✈️`, 'confirmation');
      }
    },
    [commitWithDebounce, ensureBookingTypeEnabled, onToast]
  );

  // Hotel settings update handler
  const handleUpdateHotelSettings = useCallback(
    (settings: Partial<HotelSettings>) => {
      markSettingDirty('hotel_settings');
      ensureBookingTypeEnabled('hotels');
      const currentSettings = hotelSettingsRef.current;
      const newSettings = { ...currentSettings, ...settings };
      // Update ref and state synchronously so rapid clicks work correctly
      hotelSettingsRef.current = newSettings;
      setLocalHotelSettings(newSettings);

      // Sync to document store immediately so trip_inputs is up-to-date
      // (commitTripInputs is debounced — this bridges the gap)
      if (hasDocument) {
        updateTripInputs({ hotel_settings: newSettings });
      }

      // Commit with debounce (handles queue for pre-document state)
      commitWithDebounce(
        { hotel_settings: newSettings },
        hotelCommitTimer,
        hasPendingHotelChanges
      );

      // Generate confirmation toast based on what actually changed
      if ('min_stars' in settings && currentSettings.min_stars !== settings.min_stars) {
        const stars = settings.min_stars!;
        const message = stars === 0
          ? 'Removed minimum star rating requirement! 🏨'
          : `Set minimum ${stars}-star hotels! ${'⭐'.repeat(stars)}`;
        onToast(message, 'confirmation');
      }
      if ('amenities' in settings) {
        // For arrays, check if content changed (simple length + stringify comparison)
        const oldAmenities = currentSettings.amenities;
        const newAmenities = settings.amenities!;
        if (JSON.stringify(oldAmenities) !== JSON.stringify(newAmenities)) {
          if (newAmenities.length === 0) {
            onToast('Cleared hotel amenity requirements! 🏨', 'confirmation');
          } else {
            const formatted = newAmenities.map(a => a.replace('_', ' ')).join(', ');
            onToast(`Looking for hotels with: ${formatted}! 🏨`, 'confirmation');
          }
        }
      }
    },
    [commitWithDebounce, hasDocument, updateTripInputs, ensureBookingTypeEnabled, onToast]
  );

  // Transport settings update handler
  const handleUpdateTransportSettings = useCallback(
    (settings: Partial<TransportSettings>) => {
      markSettingDirty('transport_settings');
      ensureBookingTypeEnabled('ground_transport');
      const currentSettings = transportSettingsRef.current;
      const newSettings = { ...currentSettings, ...settings };
      // Update ref and state synchronously so rapid clicks work correctly
      transportSettingsRef.current = newSettings;
      setLocalTransportSettings(newSettings);

      // Commit with debounce (handles queue for pre-document state)
      commitWithDebounce(
        { transport_settings: newSettings },
        transportCommitTimer,
        hasPendingTransportChanges
      );

      // Generate confirmation toast based on what actually changed
      const modeLabels: Record<string, string> = { car: 'car rental', train: 'trains', bus: 'buses' };
      for (const [mode, enabled] of Object.entries(settings)) {
        if (mode in modeLabels) {
          // Only generate message if value actually changed
          const oldValue = currentSettings[mode as keyof TransportSettings];
          if (oldValue !== enabled) {
            const label = modeLabels[mode];
            onToast(
              enabled ? `Added ${label} to transport options! 🚗` : `Removed ${label} from transport options.`,
              'confirmation'
            );
          }
        }
      }
    },
    [commitWithDebounce, ensureBookingTypeEnabled, onToast]
  );

  // Activity settings update handler
  const handleUpdateActivitySettings = useCallback(
    (settings: Partial<ActivitySettings>) => {
      markSettingDirty('activity_settings');
      const currentSettings = activitySettingsRef.current;
      const newSettings = { ...currentSettings, ...settings };
      const hasExplicitCategoryUpdate = Object.prototype.hasOwnProperty.call(settings, 'categories');
      const nextCategories = hasExplicitCategoryUpdate
        ? (settings.categories ?? [])
        : (newSettings.categories ?? []);

      if (nextCategories.length > 0) {
        ensureBookingTypeEnabled('activities');
      } else if (hasExplicitCategoryUpdate) {
        // Explicitly clearing categories means activities are off, not "mixed fallback".
        markSettingDirty('booking_types');
        const updatedBookingTypes = { ...bookingTypesRef.current, activities: 'off' as BookingTypeState };
        bookingTypesRef.current = updatedBookingTypes;
        setLocalBookingTypes(updatedBookingTypes);
        commitWithDebounce(
          { booking_types: updatedBookingTypes },
          bookingTypesCommitTimer,
          hasPendingBookingTypesChanges
        );
      }

      // Update ref and state synchronously so rapid clicks work correctly
      activitySettingsRef.current = newSettings;
      setLocalActivitySettings(newSettings);

      // Sync to document store immediately so trip_inputs is up-to-date
      // (commitTripInputs is debounced — this bridges the gap)
      if (hasDocument) {
        updateTripInputs({ activity_settings: newSettings });
      }

      // Commit with debounce (handles queue for pre-document state)
      commitWithDebounce(
        { activity_settings: newSettings },
        activityCommitTimer,
        hasPendingActivityChanges
      );

      // Generate confirmation toast based on what actually changed
      if ('categories' in settings) {
        const newCategories = settings.categories!;
        // For arrays, check if content changed
        if (JSON.stringify(currentSettings.categories) !== JSON.stringify(newCategories)) {
          if (newCategories.length === 0) {
            onToast('Cleared all activities', 'confirmation');
          }
        }
      }
    },
    [commitWithDebounce, hasDocument, updateTripInputs, ensureBookingTypeEnabled, onToast]
  );

  // Add activity handler
  const handleAddActivity = useCallback(
    (activity: string) => {
      const trimmed = activity.trim();
      if (!trimmed) return;

      // Normalize activity with emoji prefix
      const normalized = normalizeActivityWithEmoji(trimmed);

      const currentCategories = activitySettingsRef.current.categories;
      // Check for duplicates (case-insensitive, ignoring emoji prefix)
      if (currentCategories.some((c) => areActivitiesDuplicate(c, normalized))) {
        onToast('Activity already added', 'info');
        return;
      }

      const newCategories = [...currentCategories, normalized];
      // Deduplicate to be safe (in case of edge cases)
      const deduped = deduplicateActivities(newCategories);
      handleUpdateActivitySettings({ categories: deduped });
      onToast(`Added "${trimmed}"`, 'confirmation');
    },
    [handleUpdateActivitySettings, onToast]
  );

  // Remove activity handler
  const handleRemoveActivity = useCallback(
    (index: number) => {
      const currentCategories = activitySettingsRef.current.categories;
      if (index < 0 || index >= currentCategories.length) return;

      const removed = currentCategories[index];
      const newCategories = currentCategories.filter((_, i) => i !== index);
      handleUpdateActivitySettings({ categories: newCategories });
      onToast(`Removed "${removed}"`, 'confirmation');
    },
    [handleUpdateActivitySettings, onToast]
  );

  return {
    bookingTypes: localBookingTypes,
    flightSettings: localFlightSettings,
    hotelSettings: localHotelSettings,
    transportSettings: localTransportSettings,
    activitySettings: localActivitySettings,
    handleUpdateBookingTypes,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateTransportSettings,
    handleUpdateActivitySettings,
    handleAddActivity,
    handleRemoveActivity,
  };
}
