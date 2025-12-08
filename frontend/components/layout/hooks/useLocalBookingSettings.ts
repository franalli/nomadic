'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  DEFAULT_TRIP_INPUTS,
  useDocumentStore,
} from '@/state/documentStore';
import type {
  ActivitySettings,
  BookingTypes,
  DocumentTripInputs,
  DocumentTripInputsPatch,
  FlightSettings,
  HotelSettings,
  TransportSettings,
} from '@/types/document';
import type { ToastType } from '@/types/hooks';

export interface UseLocalBookingSettingsReturn {
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
  const documentStore = useDocumentStore();
  const document = useDocumentStore((state) => state.document);

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

  // Sync local state from store when store values change (only if no pending local changes)
  // Using JSON.stringify for deep comparison to avoid unnecessary updates from reference changes
  const storeBookingTypesJson = JSON.stringify(storeTripInputs?.booking_types);
  const storeFlightSettingsJson = JSON.stringify(storeTripInputs?.flight_settings);
  const storeHotelSettingsJson = JSON.stringify(storeTripInputs?.hotel_settings);
  const storeTransportSettingsJson = JSON.stringify(storeTripInputs?.transport_settings);
  const storeActivitySettingsJson = JSON.stringify(storeTripInputs?.activity_settings);

  useEffect(() => {
    if (storeTripInputs?.booking_types && !hasPendingBookingTypesChanges.current) {
      setLocalBookingTypes(storeTripInputs.booking_types);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeBookingTypesJson]);

  useEffect(() => {
    if (storeTripInputs?.flight_settings && !hasPendingFlightChanges.current) {
      setLocalFlightSettings(storeTripInputs.flight_settings);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeFlightSettingsJson]);

  useEffect(() => {
    if (storeTripInputs?.hotel_settings && !hasPendingHotelChanges.current) {
      setLocalHotelSettings(storeTripInputs.hotel_settings);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeHotelSettingsJson]);

  useEffect(() => {
    if (storeTripInputs?.transport_settings && !hasPendingTransportChanges.current) {
      setLocalTransportSettings(storeTripInputs.transport_settings);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeTransportSettingsJson]);

  useEffect(() => {
    if (storeTripInputs?.activity_settings && !hasPendingActivityChanges.current) {
      setLocalActivitySettings(storeTripInputs.activity_settings);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeActivitySettingsJson]);

  // Flush queued commits when document becomes available
  useEffect(() => {
    if (document && pendingCommitsQueue.current) {
      const queuedCommits = pendingCommitsQueue.current;
      pendingCommitsQueue.current = null;
      // Commit all queued changes in a single batched request
      documentStore.commitTripInputs(queuedCommits).then(() => {
        // Clear all pending flags after successful commit
        hasPendingBookingTypesChanges.current = false;
        hasPendingFlightChanges.current = false;
        hasPendingHotelChanges.current = false;
        hasPendingTransportChanges.current = false;
        hasPendingActivityChanges.current = false;
      });
    }
  }, [document, documentStore]);

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

  // Helper to commit settings with debounce and queue support
  const commitWithDebounce = useCallback(
    (
      updates: DocumentTripInputsPatch,
      timerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | null>,
      pendingRef: React.MutableRefObject<boolean>
    ) => {
      // Mark as having pending changes
      pendingRef.current = true;

      // Clear existing timer
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      // If no document exists, queue the changes for later
      if (!document) {
        pendingCommitsQueue.current = {
          ...pendingCommitsQueue.current,
          ...updates,
        };
        return;
      }

      // Debounce the commit to batch rapid changes
      timerRef.current = setTimeout(async () => {
        const success = await documentStore.commitTripInputs(updates);
        if (success) {
          pendingRef.current = false;
        }
        // If commit failed (e.g., isCommitting lock), the pending flag stays true
        // and sync-back won't overwrite local state
      }, COMMIT_DEBOUNCE_MS);
    },
    [document, documentStore]
  );

  // Booking types update handler
  const handleUpdateBookingTypes = useCallback(
    (settings: Partial<BookingTypes>) => {
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
      for (const [type, enabled] of Object.entries(settings) as [keyof BookingTypes, boolean][]) {
        if (type in typeLabels) {
          const oldValue = currentSettings[type];
          if (oldValue !== enabled) {
            const label = typeLabels[type];
            onToast(
              enabled ? `Added ${label} to search!` : `Removed ${label} from search.`,
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
    [commitWithDebounce, onToast]
  );

  // Hotel settings update handler
  const handleUpdateHotelSettings = useCallback(
    (settings: Partial<HotelSettings>) => {
      const currentSettings = hotelSettingsRef.current;
      const newSettings = { ...currentSettings, ...settings };
      // Update ref and state synchronously so rapid clicks work correctly
      hotelSettingsRef.current = newSettings;
      setLocalHotelSettings(newSettings);

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
    [commitWithDebounce, onToast]
  );

  // Transport settings update handler
  const handleUpdateTransportSettings = useCallback(
    (settings: Partial<TransportSettings>) => {
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
    [commitWithDebounce, onToast]
  );

  // Activity settings update handler
  const handleUpdateActivitySettings = useCallback(
    (settings: Partial<ActivitySettings>) => {
      const currentSettings = activitySettingsRef.current;
      const newSettings = { ...currentSettings, ...settings };
      // Update ref and state synchronously so rapid clicks work correctly
      activitySettingsRef.current = newSettings;
      setLocalActivitySettings(newSettings);

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
            onToast('Showing all activity categories! 🎭', 'confirmation');
          } else {
            const formatted = newCategories.map(c => c.replace('_', ' & ')).join(', ');
            onToast(`Filtering activities: ${formatted}! 🎭`, 'confirmation');
          }
        }
      }
    },
    [commitWithDebounce, onToast]
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
  };
}
