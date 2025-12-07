'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ChatPanelHandle } from '@/components/chat/ChatPanel';
import {
  DEFAULT_TRIP_INPUTS,
  useDocumentStore,
} from '@/state/documentStore';
import type {
  ActivitySettings,
  DocumentTripInputs,
  DocumentTripInputsPatch,
  FlightSettings,
  HotelSettings,
  TransportSettings,
} from '@/types/document';

export interface UseLocalBookingSettingsReturn {
  flightSettings: FlightSettings;
  hotelSettings: HotelSettings;
  transportSettings: TransportSettings;
  activitySettings: ActivitySettings;
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
  chatPanelRef: React.RefObject<ChatPanelHandle | null>
): UseLocalBookingSettingsReturn {
  const documentStore = useDocumentStore();
  const document = useDocumentStore((state) => state.document);

  // Local state for booking settings - initialize from store if available, else defaults
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
  const flightSettingsRef = useRef(localFlightSettings);
  const hotelSettingsRef = useRef(localHotelSettings);
  const transportSettingsRef = useRef(localTransportSettings);
  const activitySettingsRef = useRef(localActivitySettings);

  // Refs to track if we have pending local changes that shouldn't be overwritten by store sync
  const hasPendingFlightChanges = useRef(false);
  const hasPendingHotelChanges = useRef(false);
  const hasPendingTransportChanges = useRef(false);
  const hasPendingActivityChanges = useRef(false);

  // Debounce timers for each settings type
  const flightCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hotelCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transportCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activityCommitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Queue for pre-document changes - flushed when document becomes available
  const pendingCommitsQueue = useRef<DocumentTripInputsPatch | null>(null);

  // Keep refs in sync with state
  useEffect(() => { flightSettingsRef.current = localFlightSettings; }, [localFlightSettings]);
  useEffect(() => { hotelSettingsRef.current = localHotelSettings; }, [localHotelSettings]);
  useEffect(() => { transportSettingsRef.current = localTransportSettings; }, [localTransportSettings]);
  useEffect(() => { activitySettingsRef.current = localActivitySettings; }, [localActivitySettings]);

  // Sync local state from store when store values change (only if no pending local changes)
  // Using JSON.stringify for deep comparison to avoid unnecessary updates from reference changes
  const storeFlightSettingsJson = JSON.stringify(storeTripInputs?.flight_settings);
  const storeHotelSettingsJson = JSON.stringify(storeTripInputs?.hotel_settings);
  const storeTransportSettingsJson = JSON.stringify(storeTripInputs?.transport_settings);
  const storeActivitySettingsJson = JSON.stringify(storeTripInputs?.activity_settings);

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
        chatPanelRef.current?.addAssistantMessage(`Updated flight settings: ${messages.join(', ')}! ✈️`);
      }
    },
    [commitWithDebounce, chatPanelRef]
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

      // Generate assistant message based on what actually changed
      if ('min_stars' in settings && currentSettings.min_stars !== settings.min_stars) {
        const stars = settings.min_stars!;
        const message = stars === 0
          ? 'Removed minimum star rating requirement! 🏨'
          : `Set minimum ${stars}-star hotels! ${'⭐'.repeat(stars)}`;
        chatPanelRef.current?.addAssistantMessage(message);
      }
      if ('amenities' in settings) {
        // For arrays, check if content changed (simple length + stringify comparison)
        const oldAmenities = currentSettings.amenities;
        const newAmenities = settings.amenities!;
        if (JSON.stringify(oldAmenities) !== JSON.stringify(newAmenities)) {
          if (newAmenities.length === 0) {
            chatPanelRef.current?.addAssistantMessage('Cleared hotel amenity requirements! 🏨');
          } else {
            const formatted = newAmenities.map(a => a.replace('_', ' ')).join(', ');
            chatPanelRef.current?.addAssistantMessage(`Looking for hotels with: ${formatted}! 🏨`);
          }
        }
      }
    },
    [commitWithDebounce, chatPanelRef]
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

      // Generate assistant message based on what actually changed
      const modeLabels: Record<string, string> = { car: 'car rental', train: 'trains', bus: 'buses' };
      for (const [mode, enabled] of Object.entries(settings)) {
        if (mode in modeLabels) {
          // Only generate message if value actually changed
          const oldValue = currentSettings[mode as keyof TransportSettings];
          if (oldValue !== enabled) {
            const label = modeLabels[mode];
            chatPanelRef.current?.addAssistantMessage(
              enabled ? `Added ${label} to transport options! 🚗` : `Removed ${label} from transport options.`
            );
          }
        }
      }
    },
    [commitWithDebounce, chatPanelRef]
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

      // Generate assistant message based on what actually changed
      if ('categories' in settings) {
        const newCategories = settings.categories!;
        // For arrays, check if content changed
        if (JSON.stringify(currentSettings.categories) !== JSON.stringify(newCategories)) {
          if (newCategories.length === 0) {
            chatPanelRef.current?.addAssistantMessage('Showing all activity categories! 🎭');
          } else {
            const formatted = newCategories.map(c => c.replace('_', ' & ')).join(', ');
            chatPanelRef.current?.addAssistantMessage(`Filtering activities: ${formatted}! 🎭`);
          }
        }
      }
      if ('max_duration_hours' in settings && currentSettings.max_duration_hours !== settings.max_duration_hours) {
        const hours = settings.max_duration_hours;
        const message = hours === null
          ? 'Removed activity duration limit! 🎭'
          : `Set max activity duration to ${hours} hour${hours === 1 ? '' : 's'}! 🎭`;
        chatPanelRef.current?.addAssistantMessage(message);
      }
    },
    [commitWithDebounce, chatPanelRef]
  );

  return {
    flightSettings: localFlightSettings,
    hotelSettings: localHotelSettings,
    transportSettings: localTransportSettings,
    activitySettings: localActivitySettings,
    handleUpdateFlightSettings,
    handleUpdateHotelSettings,
    handleUpdateTransportSettings,
    handleUpdateActivitySettings,
  };
}
