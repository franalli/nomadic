/**
 * Centralized state store for PlanDocument using Zustand.
 * This is the single source of truth for branches and tiles in the frontend.
 */

import { create } from 'zustand';

import { apiFetch } from '@/lib/api';
import type {
  ActivitySettings,
  BookingTypes,
  BranchSelections,
  DocumentTripInputs,
  DocumentTripInputsPatch,
  FlightSettings,
  HotelSettings,
  PlanDocumentData,
  PlanDocumentPatch,
  PlanDocumentResponse,
  TransportSettings,
  UpdatedBy,
} from '@/types/document';
import type { DayCard, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Default Settings
// NOTE: These values MUST match backend/app/schemas.py defaults.
// When adding/removing trip inputs, update backend first, then here.
// ─────────────────────────────────────────────────────────────────────────────

export const DEFAULT_BOOKING_TYPES: BookingTypes = {
  hotels: 'suggested',
  flights: 'off',  // Upgrades to 'suggested' when origin is set
  ground_transport: 'off',
  activities: 'suggested',
};

export const DEFAULT_FLIGHT_SETTINGS: FlightSettings = {
  round_trip: true,
  cabin_class: 'economy',
  direct_only: false,
};

export const DEFAULT_HOTEL_SETTINGS: HotelSettings = {
  min_stars: 0,
  amenities: [],
};

export const DEFAULT_ACTIVITY_SETTINGS: ActivitySettings = {
  categories: [],
  skill_level: null,
};

export const DEFAULT_TRANSPORT_SETTINGS: TransportSettings = {
  car: false,
  train: false,
  bus: false,
};

/**
 * Default trip inputs when no document exists yet.
 * Exported so components can use the same defaults.
 *
 * Note: missing_fields is pre-populated because the backend dynamically
 * recomputes it based on actual values during merge operations.
 */
export const DEFAULT_TRIP_INPUTS: DocumentTripInputs = {
  destination: null,
  origin: null,
  start_date: null,
  end_date: null,
  adults: null,
  children: null,
  requires_assistance: null,
  budget: null,
  currency: 'USD',
  // Per YC demo spec: destination + dates (or flexible dates) required to generate a plan
  missing_fields: ['destination'],
  booking_types: DEFAULT_BOOKING_TYPES,
  flight_settings: DEFAULT_FLIGHT_SETTINGS,
  hotel_settings: DEFAULT_HOTEL_SETTINGS,
  activity_settings: DEFAULT_ACTIVITY_SETTINGS,
  transport_settings: DEFAULT_TRANSPORT_SETTINGS,
  // Flexible dates support
  date_flex: false,
  trip_duration: null,
  date_window_start: null,
  date_window_end: null,
};

/**
 * Fields that can be tracked for LLM updates.
 * Used to show sparkle animation when LLM modifies trip inputs.
 */
export type LLMUpdatableField =
  // Core trip inputs
  | 'origin'
  | 'destination'
  | 'start_date'
  | 'end_date'
  | 'adults'
  | 'children'
  | 'requires_assistance'
  | 'budget'
  | 'currency'
  // Settings objects (parent level)
  | 'booking_types'
  | 'flight_settings'
  | 'hotel_settings'
  | 'activity_settings'
  | 'transport_settings'
  // Booking types sub-fields
  | 'booking_types.flights'
  | 'booking_types.hotels'
  | 'booking_types.ground_transport'
  | 'booking_types.activities'
  // Flight settings sub-fields
  | 'flight_settings.round_trip'
  | 'flight_settings.direct_only'
  | 'flight_settings.cabin_class'
  // Hotel settings sub-fields
  | 'hotel_settings.min_stars'
  | 'hotel_settings.amenities'
  // Activity settings sub-fields
  | 'activity_settings.categories'
  // Transport settings sub-fields
  | 'transport_settings.car'
  | 'transport_settings.train'
  | 'transport_settings.bus';

// ─────────────────────────────────────────────────────────────────────────────
// Commit Mutex
// ─────────────────────────────────────────────────────────────────────────────
// Prevents concurrent commit operations using a Promise-based lock.
// This avoids race conditions between the isCommitting check and set.
let _commitLock: Promise<void> | null = null;

async function acquireCommitLock(): Promise<boolean> {
  if (_commitLock) {
    // Another commit is in progress
    return false;
  }
  let release: () => void;
  _commitLock = new Promise((resolve) => {
    release = resolve;
  });
  // Return a release function to be called when done
  (acquireCommitLock as { release?: () => void }).release = () => {
    _commitLock = null;
    release!();
  };
  return true;
}

function releaseCommitLock(): void {
  const release = (acquireCommitLock as { release?: () => void }).release;
  if (release) {
    release();
  }
}

type DocumentState = {
  // Document data
  version: number;
  updatedBy: UpdatedBy | null;
  updatedAt: string | null;
  document: PlanDocumentData | null;

  // UI state
  selectedBranchId: string | null;
  isLoading: boolean;
  isCommitting: boolean;
  error: string | null;

  // View navigation (two-mode system: PLANNING + BOOKING)
  activeView: 'planning' | 'booking';
  setActiveView: (view: 'planning' | 'booking') => void;

  // Plan finalization (gates Book view access)
  isPlanFinalized: boolean;
  setFinalized: (finalized: boolean) => void;

  // Heart preference system (PLANNING mode - preference signals for AI weighting)
  preferredTileIds: Set<string>;
  toggleTilePreference: (tileId: string) => void;
  clearPreferences: () => void;
  // Track pending preference PATCH to ensure persistence before regen
  pendingPreferencePatch: Promise<void> | null;
  awaitPreferencePatch: () => Promise<void>;

  // Regeneration tracking - preferences used in last expand-itinerary call
  lastGeneratedPreferences: Set<string>;
  markPreferencesAsApplied: () => void;

  // Regeneration UI state (shared across components)
  isRegenerating: boolean;
  isPending: boolean;
  remainingSeconds: number;
  setRegenerationState: (state: { isRegenerating?: boolean; isPending?: boolean; remainingSeconds?: number }) => void;

  // Cart state (for BOOKING mode)
  cartTileIds: Set<string>;
  addToCart: (tileId: string) => void;
  removeFromCart: (tileId: string) => void;
  clearCart: () => void;

  // LLM update tracking - fields that were recently updated by the planner
  llmUpdatedFields: Set<LLMUpdatableField>;

  // Streaming robustness - runId + abort tracking
  currentRunId: string | null;
  abortController: AbortController | null;

  // Trip input selectors (computed from document)
  hasAllRequiredFields: () => boolean;

  // Trip input actions
  /** Sync update trip inputs locally (no API call). Used for immediate state updates. */
  updateTripInputs: (updates: Partial<DocumentTripInputs>) => void;
  /** Async commit trip inputs to backend with validation. */
  commitTripInputs: (updates: DocumentTripInputsPatch) => Promise<boolean>;

  // Actions
  fetchDocument: () => Promise<PlanDocumentData | null>;
  patchDocument: (patch: PlanDocumentPatch) => Promise<void>;

  // Selection actions (use patchDocument internally)
  selectTile: (
    branchId: string,
    tileId: string,
    tileType: 'stay' | 'flight' | 'activity'
  ) => Promise<void>;
  deselectTile: (
    branchId: string,
    tileType: 'stay' | 'flight' | 'activity',
    tileId?: string
  ) => Promise<void>;

  // Set document from graph plan response (when /api/graph_plan returns new document)
  setFromPlanResponse: (response: PlanDocumentResponse) => void;

  // Merge partial envelope update (used for streaming updates)
  mergeEnvelope: (envelope: Partial<PlanDocumentData>) => void;

  // Restore trip inputs from a snapshot (used when undoing a message)
  restoreTripInputs: (tripInputs: DocumentTripInputs) => void;

  // Clear sparkle for a field when user interacts with it
  acknowledgeLLMUpdate: (field: LLMUpdatableField) => void;

  // Speculative execution actions (preload specialist content during Setup)
  /** Merge specialist sections from speculative execution (upsert by specialist_type) */
  mergeSpeculativeContent: (sections: StrategySection[]) => void;
  /** Clear all speculative content (when destination changes) */
  clearSpeculativeContent: () => void;

  // Streaming robustness actions
  /** Start a new generation run - returns AbortController for the caller, or null if already running */
  startGeneration: (runId: string) => AbortController | null;
  /** Abort the current generation (if any) */
  abortGeneration: () => void;
  /** Check if a runId is the current run (ignore late events from stale runs) */
  isCurrentRun: (runId: string) => boolean;

  // Reset
  reset: () => void;
};

// NOTE: Heart preferences are now persisted to DB via PATCH /api/document
// SessionStorage is no longer used - preferences are hydrated from API response

const initialState = {
  version: 0,
  updatedBy: null as UpdatedBy | null,
  updatedAt: null as string | null,
  document: null as PlanDocumentData | null,
  selectedBranchId: null as string | null,
  isLoading: false,
  isCommitting: false,
  error: null as string | null,
  llmUpdatedFields: new Set<LLMUpdatableField>(),
  // Streaming robustness
  currentRunId: null as string | null,
  abortController: null as AbortController | null,
  // View navigation (two-mode system)
  activeView: 'planning' as const,
  // Plan finalization
  isPlanFinalized: false,
  // Heart preference system
  preferredTileIds: new Set<string>(),
  pendingPreferencePatch: null,
  // Regeneration tracking
  lastGeneratedPreferences: new Set<string>(),
  // Regeneration UI state (shared across components)
  isRegenerating: false,
  isPending: false,
  remainingSeconds: 0,
  // Cart state
  cartTileIds: new Set<string>(),
};

/**
 * 8.1.1: Shallow array comparison (avoids JSON.stringify)
 * Compares arrays by length and element-wise equality.
 */
function arraysEqual<T>(a: T[] | undefined, b: T[] | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/**
 * 8.1.1: Shallow object comparison for settings objects (avoids JSON.stringify)
 * Compares objects by their own enumerable properties.
 */
function shallowObjectEqual<T extends Record<string, unknown>>(
  a: T | undefined,
  b: T | undefined
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    const valA = a[key];
    const valB = b[key];
    // For nested arrays, use arraysEqual
    if (Array.isArray(valA) && Array.isArray(valB)) {
      if (!arraysEqual(valA, valB)) return false;
    } else if (valA !== valB) {
      return false;
    }
  }
  return true;
}

/**
 * Compare two trip inputs and return which fields changed.
 * 8.1.1: Optimized to use shallow comparison instead of JSON.stringify (32x perf improvement)
 */
function detectChangedFields(
  oldInputs: DocumentTripInputs | undefined,
  newInputs: DocumentTripInputs
): LLMUpdatableField[] {
  const changed: LLMUpdatableField[] = [];

  if (!oldInputs) {
    // If no old inputs, check which fields have values (differ from defaults)
    if (newInputs.origin) changed.push('origin');
    if (newInputs.destination) changed.push('destination');
    if (newInputs.start_date) changed.push('start_date');
    if (newInputs.end_date) changed.push('end_date');
    if (newInputs.adults != null) changed.push('adults');
    if (newInputs.children != null) changed.push('children');
    if (newInputs.requires_assistance != null) changed.push('requires_assistance');
    if (newInputs.budget != null) changed.push('budget');
    if (newInputs.currency && newInputs.currency !== DEFAULT_TRIP_INPUTS.currency) changed.push('currency');

    // Booking types - use shallow comparison
    const newBooking = newInputs.booking_types;
    const defBooking = DEFAULT_BOOKING_TYPES;
    if (!shallowObjectEqual(newBooking, defBooking)) {
      changed.push('booking_types');
      if (newBooking?.flights !== defBooking.flights) changed.push('booking_types.flights');
      if (newBooking?.hotels !== defBooking.hotels) changed.push('booking_types.hotels');
      if (newBooking?.ground_transport !== defBooking.ground_transport) changed.push('booking_types.ground_transport');
      if (newBooking?.activities !== defBooking.activities) changed.push('booking_types.activities');
    }

    // Flight settings - use shallow comparison
    const newFlight = newInputs.flight_settings;
    const defFlight = DEFAULT_FLIGHT_SETTINGS;
    if (!shallowObjectEqual(newFlight, defFlight)) {
      changed.push('flight_settings');
      if (newFlight?.round_trip !== defFlight.round_trip) changed.push('flight_settings.round_trip');
      if (newFlight?.direct_only !== defFlight.direct_only) changed.push('flight_settings.direct_only');
      if (newFlight?.cabin_class !== defFlight.cabin_class) changed.push('flight_settings.cabin_class');
    }

    // Hotel settings - use shallow comparison (handles amenities array internally)
    const newHotel = newInputs.hotel_settings;
    const defHotel = DEFAULT_HOTEL_SETTINGS;
    if (!shallowObjectEqual(newHotel, defHotel)) {
      changed.push('hotel_settings');
      if (newHotel?.min_stars !== defHotel.min_stars) changed.push('hotel_settings.min_stars');
      if (!arraysEqual(newHotel?.amenities, defHotel.amenities)) changed.push('hotel_settings.amenities');
    }

    // Activity settings - use shallow comparison (handles categories array internally)
    const newActivity = newInputs.activity_settings;
    const defActivity = DEFAULT_ACTIVITY_SETTINGS;
    if (!shallowObjectEqual(newActivity, defActivity)) {
      changed.push('activity_settings');
      if (!arraysEqual(newActivity?.categories, defActivity.categories)) changed.push('activity_settings.categories');
    }

    // Transport settings - use shallow comparison
    const newTransport = newInputs.transport_settings;
    const defTransport = DEFAULT_TRANSPORT_SETTINGS;
    if (!shallowObjectEqual(newTransport, defTransport)) {
      changed.push('transport_settings');
      if (newTransport?.car !== defTransport.car) changed.push('transport_settings.car');
      if (newTransport?.train !== defTransport.train) changed.push('transport_settings.train');
      if (newTransport?.bus !== defTransport.bus) changed.push('transport_settings.bus');
    }

    return changed;
  }

  // Compare each field
  if (oldInputs.origin !== newInputs.origin) changed.push('origin');
  if (oldInputs.destination !== newInputs.destination) changed.push('destination');
  if (oldInputs.start_date !== newInputs.start_date) changed.push('start_date');
  if (oldInputs.end_date !== newInputs.end_date) changed.push('end_date');
  if (oldInputs.adults !== newInputs.adults) changed.push('adults');
  if (oldInputs.children !== newInputs.children) changed.push('children');
  if (oldInputs.requires_assistance !== newInputs.requires_assistance) changed.push('requires_assistance');
  if (oldInputs.budget !== newInputs.budget) changed.push('budget');
  if (oldInputs.currency !== newInputs.currency) changed.push('currency');

  // Booking types - use shallow comparison
  const oldBooking = oldInputs.booking_types;
  const newBooking = newInputs.booking_types;
  if (!shallowObjectEqual(oldBooking, newBooking)) {
    changed.push('booking_types');
    if (oldBooking?.flights !== newBooking?.flights) changed.push('booking_types.flights');
    if (oldBooking?.hotels !== newBooking?.hotels) changed.push('booking_types.hotels');
    if (oldBooking?.ground_transport !== newBooking?.ground_transport) changed.push('booking_types.ground_transport');
    if (oldBooking?.activities !== newBooking?.activities) changed.push('booking_types.activities');
  }

  // Flight settings - use shallow comparison
  const oldFlight = oldInputs.flight_settings;
  const newFlight = newInputs.flight_settings;
  if (!shallowObjectEqual(oldFlight, newFlight)) {
    changed.push('flight_settings');
    if (oldFlight?.round_trip !== newFlight?.round_trip) changed.push('flight_settings.round_trip');
    if (oldFlight?.direct_only !== newFlight?.direct_only) changed.push('flight_settings.direct_only');
    if (oldFlight?.cabin_class !== newFlight?.cabin_class) changed.push('flight_settings.cabin_class');
  }

  // Hotel settings - use shallow comparison
  const oldHotel = oldInputs.hotel_settings;
  const newHotel = newInputs.hotel_settings;
  if (!shallowObjectEqual(oldHotel, newHotel)) {
    changed.push('hotel_settings');
    if (oldHotel?.min_stars !== newHotel?.min_stars) changed.push('hotel_settings.min_stars');
    if (!arraysEqual(oldHotel?.amenities, newHotel?.amenities)) changed.push('hotel_settings.amenities');
  }

  // Activity settings - use shallow comparison
  const oldActivity = oldInputs.activity_settings;
  const newActivity = newInputs.activity_settings;
  if (!shallowObjectEqual(oldActivity, newActivity)) {
    changed.push('activity_settings');
    if (!arraysEqual(oldActivity?.categories, newActivity?.categories)) changed.push('activity_settings.categories');
  }

  // Transport settings - use shallow comparison
  const oldTransport = oldInputs.transport_settings;
  const newTransport = newInputs.transport_settings;
  if (!shallowObjectEqual(oldTransport, newTransport)) {
    changed.push('transport_settings');
    if (oldTransport?.car !== newTransport?.car) changed.push('transport_settings.car');
    if (oldTransport?.train !== newTransport?.train) changed.push('transport_settings.train');
    if (oldTransport?.bus !== newTransport?.bus) changed.push('transport_settings.bus');
  }

  return changed;
}

export const useDocumentStore = create<DocumentState>((set, get) => ({
  ...initialState,

  // Trip input selectors
  // Per YC demo spec: only destination is required to generate a plan
  // Other fields (origin, dates) are optional accelerators, not blockers
  hasAllRequiredFields: () => {
    const { document } = get();
    const tripInputs = document?.trip_inputs;

    // Only require destination - everything else is optional
    const hasDestination = Boolean(tripInputs?.destination);

    return hasDestination;
  },

  // Trip input actions

  // Sync update trip inputs locally (no API call)
  // Used for immediate state updates before validation completes
  updateTripInputs: (updates) => {
    console.log('[documentStore] 🔄 updateTripInputs CALLED with:', updates);
    const { document } = get();
    if (!document) {
      console.warn('[documentStore] updateTripInputs: No document exists yet');
      return;
    }

    const previousDestination = document.trip_inputs?.destination;
    const newDestination = updates.destination;

    // Log destination change for debugging (tiles cleared by backend on GENERATE_PLAN_NOW)
    if (newDestination && newDestination !== previousDestination) {
      console.log('[documentStore] 📍 Destination changed (tiles kept until Refresh):', {
        from: previousDestination,
        to: newDestination,
      });

      // Clear stale preferences from old destination
      set({ preferredTileIds: new Set() });
      console.log('[documentStore] 🧹 Cleared preferredTileIds (destination changed)');
    }

    set({
      document: {
        ...document,
        trip_inputs: {
          ...document.trip_inputs,
          ...updates,
        },
        // NOTE: Tiles NOT cleared here - backend clears on GENERATE_PLAN_NOW (Refresh)
      },
    });

    // SYNC: Zustand set() completes before next line executes
    console.log('[documentStore] 📝 Trip inputs updated (sync):', {
      updatedFields: Object.keys(updates),
      previousDestination,
      newDestination: newDestination || 'unchanged',
      currentDestination: get().document?.trip_inputs?.destination,
    });
  },

  commitTripInputs: async (updates: DocumentTripInputsPatch): Promise<boolean> => {
    // Atomic lock acquisition - prevents concurrent commits via Promise-based mutex
    const acquired = await acquireCommitLock();
    if (!acquired) {
      // Another commit is in progress
      return false;
    }

    let { document, version } = get();

    // If no document exists yet, create a minimal document structure
    // This allows users to set trip inputs via sheets before sending a chat message
    if (!document) {
      document = {
        trip_context_id: null,
        trip_inputs: { ...DEFAULT_TRIP_INPUTS },
        branches: [],
        tiles: {},
        plan_view_state: 'S0_BOOTSTRAP',
      };
      version = 0; // New document starts at version 0
      // Initialize the store with the minimal document
      set({ document, version });
    }

    // Mark as committing (for UI feedback)
    set({ isCommitting: true });

    try {
      // Store previous state for rollback
      const previousTripInputs = document.trip_inputs;

      // Optimistically update trip inputs - let backend be authoritative for missing_fields
      // We don't compute missing_fields here; the backend recomputes it on every PATCH response
      const updatedTripInputs: DocumentTripInputs = {
        ...document.trip_inputs,
        ...updates,
        // Keep current missing_fields until backend responds with authoritative value
        missing_fields: document.trip_inputs.missing_fields ?? [],
      };

      // Optimistically update the store
      set({
        document: {
          ...document,
          trip_inputs: updatedTripInputs,
        },
      });

      // Helper to attempt PATCH with given version
      const attemptPatch = async (patchVersion: number): Promise<PlanDocumentResponse> => {
        const patch: PlanDocumentPatch = {
          version: patchVersion,
          trip_inputs: updates,
        };

        const res = await apiFetch('/api/document', {
          method: 'PATCH',
          body: JSON.stringify(patch),
        });
        if (!res.ok) {
          throw new Error(`${res.status}`);
        }
        return res.json();
      };

      // Send to backend
      try {
        const response = await attemptPatch(version);

        // Get current document to preserve strategy fields
        // Strategy fields come from graph SSE response, not persisted in DB
        // PATCH response doesn't include them, so we must preserve them
        const currentDoc = get().document;

        // Update with backend response, but preserve strategy fields from current state
        set({
          version: response.version,
          updatedBy: response.updated_by,
          updatedAt: response.updated_at,
          document: {
            ...response.document,
            // Preserve strategy fields from graph (not persisted in DB)
            strategy_sections: currentDoc?.strategy_sections ?? response.document.strategy_sections,
            executed_strategy_topics: currentDoc?.executed_strategy_topics ?? response.document.executed_strategy_topics,
            pending_strategy_topics: currentDoc?.pending_strategy_topics ?? response.document.pending_strategy_topics,
            plan_view_state: currentDoc?.plan_view_state ?? response.document.plan_view_state,
            // Also preserve tiles which may come from graph
            tiles: currentDoc?.tiles && Object.keys(currentDoc.tiles).length > 0
              ? currentDoc.tiles
              : response.document.tiles,
          },
          isCommitting: false,
          error: null,
        });

        return true;
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : '';

        // Handle 409 Conflict (version mismatch) - refetch and retry once
        if (errorMessage.includes('409')) {
          try {
            // Fetch fresh document state
            const freshRes = await apiFetch('/api/document');
            if (!freshRes.ok) {
              throw new Error('Failed to refresh document');
            }
            const freshResponse: PlanDocumentResponse = await freshRes.json();

            // Retry with fresh version
            const retryResponse = await attemptPatch(freshResponse.version);

            // Get current document to preserve strategy fields
            const currentDocRetry = get().document;

            // Update with retry response, preserving strategy fields
            set({
              version: retryResponse.version,
              updatedBy: retryResponse.updated_by,
              updatedAt: retryResponse.updated_at,
              document: {
                ...retryResponse.document,
                // Preserve strategy fields from graph (not persisted in DB)
                strategy_sections: currentDocRetry?.strategy_sections ?? retryResponse.document.strategy_sections,
                executed_strategy_topics: currentDocRetry?.executed_strategy_topics ?? retryResponse.document.executed_strategy_topics,
                pending_strategy_topics: currentDocRetry?.pending_strategy_topics ?? retryResponse.document.pending_strategy_topics,
                plan_view_state: currentDocRetry?.plan_view_state ?? retryResponse.document.plan_view_state,
                tiles: currentDocRetry?.tiles && Object.keys(currentDocRetry.tiles).length > 0
                  ? currentDocRetry.tiles
                  : retryResponse.document.tiles,
              },
              isCommitting: false,
              error: null,
            });

            return true;
          } catch (retryErr) {
            // Retry failed - rollback
            set({
              document: {
                ...document,
                trip_inputs: previousTripInputs,
              },
              isCommitting: false,
              error: retryErr instanceof Error ? retryErr.message : 'Failed to update trip inputs',
            });
            return false;
          }
        }

        // Handle 404 (document doesn't exist on backend yet) - keep local state
        // The document will be created when user sends first chat message via graph_plan
        // We don't rollback because the user should see their changes in the UI
        if (errorMessage.includes('404')) {
          set({ isCommitting: false, error: null });
          // Return true because the local state was updated successfully
          // Backend sync will happen when document is created
          return true;
        }

        // Other non-409 errors - rollback
        set({
          document: {
            ...document,
            trip_inputs: previousTripInputs,
          },
          isCommitting: false,
          error: errorMessage || 'Failed to update trip inputs',
        });
        return false;
      }
    } finally {
      // Always release the commit lock
      releaseCommitLock();
    }
  },

  fetchDocument: async () => {
    console.log('[documentStore.fetchDocument] 🚀 Starting fetch...');
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/api/document');
      console.log('[documentStore.fetchDocument] 📡 Response status:', res.status);

      // Handle 204 No Content FIRST (before trying to parse JSON)
      // 204 is a success status (res.ok=true) but has no body
      if (res.status === 204) {
        console.log('[documentStore.fetchDocument] ⚠️ No document (204 No Content)');
        set({ isLoading: false, document: null });
        return null;
      }

      if (!res.ok) {
        if (res.status === 404) {
          // 404: Legacy handling for no document
          console.log('[documentStore.fetchDocument] ⚠️ No document (404)');
          set({ isLoading: false, document: null });
          return null;
        }
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      // DEBUG: Log document details
      console.log('[documentStore.fetchDocument] Response:', {
        tilesCount: Object.keys(response.document.tiles ?? {}).length,
        preferredTileIds: response.document.preferred_tile_ids,
        branchesCount: response.document.branches?.length ?? 0,
      });
      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: response.document,
        isLoading: false,
        // Auto-select primary branch if none selected
        selectedBranchId:
          get().selectedBranchId ||
          response.document.branches.find((b) => b.is_primary)?.id ||
          response.document.branches[0]?.id ||
          null,
        // Hydrate preferences from DB (replaces sessionStorage)
        preferredTileIds: new Set(response.document.preferred_tile_ids ?? []),
      });
      return response.document;
    } catch (err) {
      console.error('[documentStore.fetchDocument] ❌ Error:', err);
      const message = err instanceof Error ? err.message : 'Failed to fetch document';
      set({ isLoading: false, error: message });
      return null;
    }
  },

  patchDocument: async (patch: PlanDocumentPatch) => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/api/document', {
        method: 'PATCH',
        body: JSON.stringify(patch),
      });
      if (!res.ok) {
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      const { document: currentDoc } = get();

      // MERGE: Preserve frontend-only fields not stored in DB
      // Backend PATCH only updates trip_inputs, branches, selections
      // Frontend-only: plan_view_state, strategy_sections, tiles, generation, etc.
      const mergedDocument = {
        ...currentDoc,        // Keep existing frontend state
        ...response.document, // Apply PATCH updates (trip_inputs, branches, etc.)
        // Explicitly preserve fields that SSE sets but DB doesn't store:
        plan_view_state: currentDoc?.plan_view_state ?? response.document.plan_view_state,
        strategy_sections: currentDoc?.strategy_sections ?? response.document.strategy_sections,
        executed_strategy_topics: currentDoc?.executed_strategy_topics ?? response.document.executed_strategy_topics,
        tiles: currentDoc?.tiles && Object.keys(currentDoc.tiles).length > 0
          ? currentDoc.tiles
          : response.document.tiles,
        generation: currentDoc?.generation,
        open_decisions: currentDoc?.open_decisions ?? response.document.open_decisions,
      };

      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: mergedDocument,
        isLoading: false,
      });
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Failed to update document',
      });
    }
  },

  selectTile: async (
    branchId: string,
    tileId: string,
    tileType: 'stay' | 'flight' | 'activity'
  ) => {
    const { document, version } = get();
    if (!document) return;

    const branch = document.branches.find((b) => b.id === branchId);
    if (!branch) return;

    // Build updated selections
    const updatedSelections: BranchSelections = { ...branch.selections };
    if (tileType === 'stay') {
      updatedSelections.stay = tileId;
    } else if (tileType === 'flight') {
      updatedSelections.flight = tileId;
    } else if (tileType === 'activity') {
      if (!updatedSelections.activities.includes(tileId)) {
        updatedSelections.activities = [...updatedSelections.activities, tileId];
      }
    }

    const patch: PlanDocumentPatch = {
      version,
      selections: { [branchId]: updatedSelections },
    };

    await get().patchDocument(patch);
  },

  deselectTile: async (
    branchId: string,
    tileType: 'stay' | 'flight' | 'activity',
    tileId?: string
  ) => {
    const { document, version } = get();
    if (!document) return;

    const branch = document.branches.find((b) => b.id === branchId);
    if (!branch) return;

    // Build updated selections
    const updatedSelections: BranchSelections = { ...branch.selections };
    if (tileType === 'stay') {
      updatedSelections.stay = null;
    } else if (tileType === 'flight') {
      updatedSelections.flight = null;
    } else if (tileType === 'activity' && tileId) {
      updatedSelections.activities = updatedSelections.activities.filter(
        (id) => id !== tileId
      );
    }

    const patch: PlanDocumentPatch = {
      version,
      selections: { [branchId]: updatedSelections },
    };

    await get().patchDocument(patch);
  },

  setFromPlanResponse: (response: PlanDocumentResponse) => {
    const { document: currentDoc, llmUpdatedFields } = get();
    const primaryBranch = response.document.branches.find((b) => b.is_primary);

    // ============================================================
    // DESTINATION CHANGE DETECTION (same as mergeEnvelope)
    // ============================================================
    const prevDestination = currentDoc?.trip_inputs?.destination?.toLowerCase().trim();
    const newDestination = response.document.trip_inputs?.destination?.toLowerCase().trim();
    const destinationChanged = prevDestination && newDestination && prevDestination !== newDestination;

    if (destinationChanged) {
      console.log(
        `[documentStore.setFromPlanResponse] 🌍 Destination changed: "${prevDestination}" → "${newDestination}"`
      );
      // Clear chat messages on destination change

      const { useChatStore } = require('./chatStore');
      useChatStore.getState().resetChat();
      console.log('[documentStore.setFromPlanResponse] 💬 Chat: CLEARED (destination changed)');
    }

    // Detect view state revert (S3 → S2)
    const prevViewState = currentDoc?.plan_view_state;
    const newViewState = response.document.plan_view_state;
    const viewStateReverted = prevViewState === 'S3_ITINERARY_READY' && newViewState === 'S2_STRATEGY_READY';

    if (viewStateReverted) {
      console.log(`[documentStore.setFromPlanResponse] 🔄 View state reverted: ${prevViewState} → ${newViewState}`);
    }

    // DEBUG: Log document state when setting
    console.log('[documentStore] setFromPlanResponse:', {
      strategy_sections_count: response.document.strategy_sections?.length ?? 0,
      strategy_sections: response.document.strategy_sections,
      plan_view_state: response.document.plan_view_state,
      executed_strategy_topics: response.document.executed_strategy_topics,
      tiles_count: Object.keys(response.document.tiles ?? {}).length,
      tiles_keys: Object.keys(response.document.tiles ?? {}),
      destinationChanged,
      viewStateReverted,
    });

    // Merge locally-set trip_inputs with response
    // This preserves values the user set via sheets before the first chat message
    // Strategy: For each field, use response value if it's set, otherwise keep local value
    const responseTripInputs = response.document.trip_inputs;
    const localTripInputs = currentDoc?.trip_inputs;
    const mergedTripInputs: DocumentTripInputs = {
      ...DEFAULT_TRIP_INPUTS,
      ...responseTripInputs,
      // Preserve locally-set values that backend returned as null
      destination: responseTripInputs.destination ?? localTripInputs?.destination ?? null,
      origin: responseTripInputs.origin ?? localTripInputs?.origin ?? null,
      start_date: responseTripInputs.start_date ?? localTripInputs?.start_date ?? null,
      end_date: responseTripInputs.end_date ?? localTripInputs?.end_date ?? null,
      adults: responseTripInputs.adults ?? localTripInputs?.adults ?? null,
      children: responseTripInputs.children ?? localTripInputs?.children ?? null,
      budget: responseTripInputs.budget ?? localTripInputs?.budget ?? null,
      currency: responseTripInputs.currency ?? localTripInputs?.currency ?? 'USD',
      trip_duration: responseTripInputs.trip_duration ?? localTripInputs?.trip_duration ?? null,
      date_flex: responseTripInputs.date_flex ?? localTripInputs?.date_flex ?? false,
    };

    // If update is from planner, detect which fields changed
    let newLLMUpdatedFields = llmUpdatedFields;
    if (response.updated_by === 'planner') {
      const changedFields = detectChangedFields(
        currentDoc?.trip_inputs,
        response.document.trip_inputs
      );
      if (changedFields.length > 0) {
        // Add newly changed fields to the existing set
        newLLMUpdatedFields = new Set([...llmUpdatedFields, ...changedFields]);

        // Auto-clear after 300ms for one-shot echo effect
        // Echo = visual feedback showing "where" change happened, not persistent state
        setTimeout(() => {
          set({ llmUpdatedFields: new Set() });
        }, 300);
      }
    }

    // Hydrate preferences from response (keep existing if not in response)
    const currentPreferences = get().preferredTileIds;
    const responsePreferences = response.document.preferred_tile_ids;
    const mergedPreferences = responsePreferences && responsePreferences.length > 0
      ? new Set(responsePreferences)
      : currentPreferences;

    // Clear day_cards if destination changed or view state reverted (prevent stale itinerary)
    const finalDayCards = (destinationChanged || viewStateReverted)
      ? []
      : response.document.day_cards;

    if (destinationChanged || viewStateReverted) {
      console.log('[documentStore.setFromPlanResponse] 📅 Day cards: CLEARED (destination changed or view reverted)');
    }

    set({
      version: response.version,
      updatedBy: response.updated_by,
      updatedAt: response.updated_at,
      document: {
        ...response.document,
        trip_inputs: mergedTripInputs,
        day_cards: finalDayCards,
      },
      selectedBranchId:
        get().selectedBranchId ||
        primaryBranch?.id ||
        response.document.branches[0]?.id ||
        null,
      llmUpdatedFields: newLLMUpdatedFields,
      preferredTileIds: mergedPreferences,
    });
  },

  mergeEnvelope: (envelope: Partial<PlanDocumentData>) => {
    const { document: currentDoc } = get();
    if (!currentDoc) return;

    // DEBUG: Log envelope structure for diagnostics
    console.log('[DEBUG mergeEnvelope] Envelope structure:', {
      has_trip_inputs: !!envelope.trip_inputs,
      trip_inputs_destination: envelope.trip_inputs?.destination,
      has_tiles: !!envelope.tiles,
      tiles_count: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      current_destination: currentDoc.trip_inputs?.destination,
    });

    // Detect destination change
    const prevDestination = currentDoc.trip_inputs?.destination?.toLowerCase().trim();
    const newDestination = envelope.trip_inputs?.destination?.toLowerCase().trim();
    const destinationChanged = prevDestination && newDestination && prevDestination !== newDestination;

    if (destinationChanged) {
      console.log(
        `[documentStore.mergeEnvelope] 🌍 Destination changed: "${prevDestination}" → "${newDestination}"`
      );
      // Clear chat messages on destination change (import chatStore at top of file)

      const { useChatStore } = require('./chatStore');
      useChatStore.getState().resetChat();
      console.log('[documentStore.mergeEnvelope] 💬 Chat: CLEARED (destination changed)');
    }

    // Detect plan view state revert (S3 → S2) - happens when backend says "start fresh"
    const viewStateReverted =
      currentDoc.plan_view_state === 'S3_ITINERARY_READY' &&
      envelope.plan_view_state === 'S2_STRATEGY_READY';

    if (viewStateReverted) {
      console.log('[documentStore.mergeEnvelope] 🔄 View state reverted: S3 → S2');
    }

    // DEBUG: Log what's in the envelope
    console.log('[documentStore.mergeEnvelope] 📥 Received envelope:', {
      hasTiles: envelope.tiles !== undefined,
      tilesCount: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      destinationChanged,
      viewStateReverted,
    });

    // Compute tile merge strategy BEFORE building updatedDoc
    let tilesToMerge: Record<string, Tile> | undefined;

    if (envelope.tiles !== undefined) {
      if (destinationChanged) {
        // Destination changed: REPLACE tiles (even if empty)
        tilesToMerge = envelope.tiles;
        console.log('[documentStore.mergeEnvelope] 🔄 Tiles: REPLACED (destination changed)');
      } else if (Object.keys(envelope.tiles).length > 0) {
        // Same destination + non-empty: MERGE
        tilesToMerge = envelope.tiles;
        console.log('[documentStore.mergeEnvelope] 🔄 Tiles: MERGED (same destination)');
      } else {
        // Same destination + empty: SKIP (preserve existing)
        tilesToMerge = undefined;
        console.log('[documentStore.mergeEnvelope] ⏭️ Tiles: SKIPPED (empty envelope)');
      }
    }

    // Compute strategy merge strategy (similar to tiles)
    let sectionsToMerge: StrategySection[] | undefined;

    if (envelope.strategy_sections !== undefined) {
      if (destinationChanged) {
        // Destination changed: REPLACE strategy sections (even if empty)
        sectionsToMerge = envelope.strategy_sections;
        console.log('[documentStore.mergeEnvelope] 📝 Strategy: REPLACED (destination changed)');
      } else {
        // Same destination: merge/update
        sectionsToMerge = envelope.strategy_sections;
        console.log('[documentStore.mergeEnvelope] 📝 Strategy: MERGED (same destination)');
      }
    }

    // Compute day_cards merge strategy (similar to tiles)
    // On destination change OR view state revert: CLEAR existing day_cards to prevent stale itinerary
    let dayCardsToMerge: DayCard[] | undefined;

    if (envelope.day_cards !== undefined) {
      // If day_cards explicitly provided, use them
      dayCardsToMerge = envelope.day_cards;
      console.log(`[documentStore.mergeEnvelope] 📅 Day Cards: ${envelope.day_cards.length} cards provided`);
    } else if (destinationChanged || viewStateReverted) {
      // Destination changed OR view state reverted: CLEAR day_cards
      dayCardsToMerge = [];
      console.log('[documentStore.mergeEnvelope] 📅 Day Cards: CLEARED (destination changed or view reverted)');
    }

    // Merge envelope fields into current document
    const updatedDoc: PlanDocumentData = {
      ...currentDoc,
      // Plan view state fields
      ...(envelope.plan_view_state !== undefined && { plan_view_state: envelope.plan_view_state }),
      ...(sectionsToMerge !== undefined && { strategy_sections: sectionsToMerge }),
      ...(envelope.open_decisions !== undefined && { open_decisions: envelope.open_decisions }),
      ...(envelope.itinerary_overview !== undefined && { itinerary_overview: envelope.itinerary_overview }),
      ...(dayCardsToMerge !== undefined && { day_cards: dayCardsToMerge }),
      ...(envelope.itinerary_assumptions !== undefined && { itinerary_assumptions: envelope.itinerary_assumptions }),
      ...(envelope.needs_refresh !== undefined && { needs_refresh: envelope.needs_refresh }),
      ...(envelope.can_expand_to_itinerary !== undefined && { can_expand_to_itinerary: envelope.can_expand_to_itinerary }),
      // Generation state
      ...(envelope.generation !== undefined && { generation: envelope.generation }),
      // Tiles: Apply computed merge strategy
      ...(tilesToMerge !== undefined && { tiles: tilesToMerge }),
      // Update trip_inputs if present
      ...(envelope.trip_inputs !== undefined && {
        trip_inputs: { ...currentDoc.trip_inputs, ...envelope.trip_inputs },
      }),
    };

    // DEBUG: Log final tile state
    console.log('[documentStore.mergeEnvelope] Final tiles:', {
      previousCount: Object.keys(currentDoc.tiles ?? {}).length,
      envelopeCount: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      finalCount: Object.keys(updatedDoc.tiles ?? {}).length,
    });

    set({
      document: updatedDoc,
      updatedBy: 'planner',
      updatedAt: new Date().toISOString(),
    });
  },

  restoreTripInputs: (tripInputs: DocumentTripInputs) => {
    const { document: currentDoc } = get();
    if (!currentDoc) return;

    set({
      document: {
        ...currentDoc,
        trip_inputs: tripInputs,
      },
      // Clear LLM updated fields since we're reverting
      llmUpdatedFields: new Set(),
    });
  },

  acknowledgeLLMUpdate: (field: LLMUpdatableField) => {
    const { llmUpdatedFields } = get();
    if (llmUpdatedFields.has(field)) {
      const newSet = new Set(llmUpdatedFields);
      newSet.delete(field);
      set({ llmUpdatedFields: newSet });
    }
  },

  // Speculative execution actions (preload specialist content during Setup)
  mergeSpeculativeContent: (newSections: StrategySection[]) => {
    const { document } = get();
    // Only allow merging in Bootstrap mode (Setup phase)
    if (!document || document.plan_view_state !== 'S0_BOOTSTRAP') return;

    const existing = document.strategy_sections ?? [];

    // UPSERT LOGIC: Map by specialist_type to replace old cards
    // e.g. "Diving (Bali)" replaced by "Diving (Maldives)"
    const sectionMap = new Map(existing.map((s) => [s.specialist_type, s]));

    newSections.forEach((s) => {
      // Only merge specialists, ignore general/logistics
      if (s.specialist_type !== 'general') {
        sectionMap.set(s.specialist_type, s);
      }
    });

    set({
      document: {
        ...document,
        strategy_sections: Array.from(sectionMap.values()),
      },
    });
  },

  clearSpeculativeContent: () => {
    const { document } = get();
    if (!document || document.plan_view_state !== 'S0_BOOTSTRAP') return;

    // Keep 'general' (if any), remove all specialists
    const filtered = (document.strategy_sections ?? []).filter(
      (s) => s.specialist_type === 'general'
    );

    set({
      document: {
        ...document,
        strategy_sections: filtered,
      },
    });
  },

  // Streaming robustness actions
  startGeneration: (runId: string) => {
    // ATOMIC CHECK: If there's already a running generation, don't start a new one
    // This prevents race conditions where two calls both pass the guard check
    const { currentRunId: existingRunId, abortController: existingController } = get();

    if (existingRunId && existingController && !existingController.signal.aborted) {
      // Already running - return null to signal caller should not proceed
      console.log('[documentStore] ⚠️ startGeneration REJECTED - already running:', existingRunId);
      return null;
    }

    // Abort any existing (stale) generation
    if (existingController) {
      console.log('[documentStore] 🔄 Aborting stale controller');
      existingController.abort();
    }

    // Create new controller for this run
    const controller = new AbortController();
    console.log('[documentStore] ✅ startGeneration ACCEPTED:', runId);
    set({
      currentRunId: runId,
      abortController: controller,
    });

    return controller;
  },

  abortGeneration: () => {
    const { abortController } = get();
    if (abortController) {
      abortController.abort();
    }
    set({
      currentRunId: null,
      abortController: null,
    });
  },

  isCurrentRun: (runId: string) => {
    return get().currentRunId === runId;
  },

  // View navigation action
  setActiveView: (view: 'planning' | 'booking') => {
    set({ activeView: view });
  },

  setFinalized: (finalized: boolean) => {
    set({ isPlanFinalized: finalized });
  },

  // Heart preference actions (PLANNING mode - preference signals for AI weighting)
  // Persisted to DB via PATCH /api/document, hydrated from API response
  toggleTilePreference: (tileId: string) => {
    const { preferredTileIds, version, document } = get();
    const tiles = document?.tiles ?? {};
    const newSet = new Set(preferredTileIds);

    // Get the type of tile being toggled
    const tile = tiles[tileId];
    const tileType = (tile?.type || '').toLowerCase();
    const isHotel = tileType === 'hotel' || tileType === 'stay' || tileType === 'accommodation';

    if (newSet.has(tileId)) {
      // Un-hearting: just remove
      newSet.delete(tileId);
    } else {
      // Hearting: enforce single-select for hotels
      // Hotels are "your base" - only one can be preferred at a time
      // Activities remain multi-select (distributed across days)
      if (isHotel) {
        // Clear any existing hotel preferences
        for (const existingId of newSet) {
          const existingTile = tiles[existingId];
          const existingType = (existingTile?.type || '').toLowerCase();
          if (existingType === 'hotel' || existingType === 'stay' || existingType === 'accommodation') {
            newSet.delete(existingId);
          }
        }
      }
      newSet.add(tileId);
    }
    // Optimistic update
    set({ preferredTileIds: newSet });

    // Sync to backend - track pending PATCH to ensure persistence before regen
    // Handles 409 conflicts by refetching version and retrying
    const patchPreferences = async (): Promise<void> => {
      const attemptPatch = async (patchVersion: number): Promise<Response> => {
        const patchData = {
          version: patchVersion,
          preferred_tile_ids: Array.from(newSet),
        };
        console.log('[documentStore] 💜 PATCH preferences:', patchData);
        return apiFetch('/api/document', {
          method: 'PATCH',
          body: JSON.stringify(patchData),
        });
      };

      try {
        let res = await attemptPatch(version);

        // Handle 409 Conflict (version mismatch) - refetch and retry once
        if (res.status === 409) {
          console.warn('[documentStore] 💜 Version conflict (409), refetching and retrying...');
          const freshRes = await apiFetch('/api/document');
          if (freshRes.ok) {
            const freshDoc = await freshRes.json();
            set({ version: freshDoc.version });
            res = await attemptPatch(freshDoc.version);
          }
        }

        if (res.ok) {
          const responseData = await res.json();
          set({ version: responseData.version });
          console.log('[documentStore] 💜 PATCH success, new version:', responseData.version);
        } else {
          console.error('[documentStore] 💜 PATCH failed:', res.status);
        }
      } catch (err) {
        console.error('[documentStore] 💜 PATCH error:', err);
      }
    };

    const patchPromise = patchPreferences().finally(() => {
      if (get().pendingPreferencePatch === patchPromise) {
        set({ pendingPreferencePatch: null });
      }
    });

    set({ pendingPreferencePatch: patchPromise });
  },

  // Wait for any pending preference PATCH to complete
  // Called by usePreferenceAutoRegen before triggering regen
  awaitPreferencePatch: async () => {
    const { pendingPreferencePatch } = get();
    if (pendingPreferencePatch) {
      await pendingPreferencePatch;
    }
  },

  clearPreferences: () => {
    const { version } = get();
    set({ preferredTileIds: new Set() });

    // Sync to backend
    const patch = {
      version,
      preferred_tile_ids: [],
    };
    apiFetch('/api/document', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }).catch((err) => {
      console.warn('[documentStore] Failed to clear preferences:', err);
    });
  },

  // Regeneration tracking - sync lastGeneratedPreferences after expand-itinerary completes
  markPreferencesAsApplied: () => {
    const { preferredTileIds } = get();
    console.log('[documentStore] Marking preferences as applied:', preferredTileIds.size);
    set({ lastGeneratedPreferences: new Set(preferredTileIds) });
  },

  // Regeneration UI state setter (shared across components)
  setRegenerationState: (state) => {
    set({
      ...(state.isRegenerating !== undefined && { isRegenerating: state.isRegenerating }),
      ...(state.isPending !== undefined && { isPending: state.isPending }),
      ...(state.remainingSeconds !== undefined && { remainingSeconds: state.remainingSeconds }),
    });
  },

  // Cart actions (for BOOKING mode)
  addToCart: (tileId: string) => {
    const { cartTileIds } = get();
    if (!cartTileIds.has(tileId)) {
      set({ cartTileIds: new Set([...cartTileIds, tileId]) });
    }
  },

  removeFromCart: (tileId: string) => {
    const { cartTileIds } = get();
    if (cartTileIds.has(tileId)) {
      const newSet = new Set(cartTileIds);
      newSet.delete(tileId);
      set({ cartTileIds: newSet });
    }
  },

  clearCart: () => {
    set({ cartTileIds: new Set() });
  },

  reset: () => {
    // Abort any in-flight generation on reset
    const { abortController } = get();
    if (abortController) {
      abortController.abort();
    }
    // Preferences are cleared via clearPreferences() which syncs to backend
    set({
      ...initialState,
      llmUpdatedFields: new Set(),
      activeView: 'planning',
      isPlanFinalized: false,
      preferredTileIds: new Set(),
      lastGeneratedPreferences: new Set(),
      isRegenerating: false,
      isPending: false,
      remainingSeconds: 0,
      cartTileIds: new Set(),
    });
  },
}));

// =============================================================================
// 8.1.3: Granular Selector Hooks (avoid full store subscriptions)
// =============================================================================
// These hooks subscribe to specific slices of state, reducing unnecessary re-renders.

/**
 * Subscribe to trip inputs only. Re-renders only when trip_inputs changes.
 */
export const useDocumentTripInputs = () =>
  useDocumentStore((state) => state.document?.trip_inputs);

/**
 * Subscribe to branches only. Re-renders only when branches change.
 */
export const useDocumentBranches = () =>
  useDocumentStore((state) => state.document?.branches);

/**
 * Subscribe to committing state only.
 */
export const useIsCommitting = () =>
  useDocumentStore((state) => state.isCommitting);

/**
 * Subscribe to selected branch ID only.
 */
export const useSelectedBranchId = () =>
  useDocumentStore((state) => state.selectedBranchId);

/**
 * Subscribe to LLM updated fields only.
 */
export const useLLMUpdatedFields = () =>
  useDocumentStore((state) => state.llmUpdatedFields);

/**
 * Subscribe to active view only. Used for view navigation.
 */
export const useActiveView = () =>
  useDocumentStore((state) => state.activeView);

/**
 * Get the setActiveView action. Used for view navigation.
 */
export const useSetActiveView = () =>
  useDocumentStore((state) => state.setActiveView);

/**
 * Subscribe to cart tile IDs only (for BOOKING mode).
 */
export const useCartTileIds = () =>
  useDocumentStore((state) => state.cartTileIds);

/**
 * Get cart actions. Used for adding/removing items from cart.
 */
export const useCartActions = () =>
  useDocumentStore((state) => ({
    addToCart: state.addToCart,
    removeFromCart: state.removeFromCart,
    clearCart: state.clearCart,
  }));

// =============================================================================
// Heart Preference System (PLANNING mode - preference signals for AI weighting)
// =============================================================================

/**
 * Subscribe to preferred tile IDs only. Re-renders only when preferences change.
 */
export const usePreferredTileIds = () =>
  useDocumentStore((state) => state.preferredTileIds);

/**
 * Check if a specific tile is preferred. Avoids subscribing to the whole Set.
 */
export const useTilePreference = (tileId: string) =>
  useDocumentStore((state) => state.preferredTileIds.has(tileId));

/**
 * Get preference actions. Used for toggling/clearing preferences.
 */
export const usePreferenceActions = () =>
  useDocumentStore((state) => ({
    toggleTilePreference: state.toggleTilePreference,
    clearPreferences: state.clearPreferences,
  }));

/**
 * Hydrate preferences from API response (not sessionStorage).
 * This is now called automatically by fetchDocument and setFromPlanResponse.
 * Kept for backward compatibility but does nothing - preferences come from DB.
 */
export const hydratePreferences = () => {
  // No-op: Preferences are hydrated from API response in fetchDocument/setFromPlanResponse
  // See preferred_tile_ids in PlanDocumentData
};
