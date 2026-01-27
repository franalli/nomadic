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
import type { StrategySection } from '@/types/plan-envelope';

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

  // View navigation (decoupled from plan_view_state)
  activeView: 'setup' | 'plan' | 'book';
  setActiveView: (view: 'setup' | 'plan' | 'book') => void;

  // LLM update tracking - fields that were recently updated by the planner
  llmUpdatedFields: Set<LLMUpdatableField>;

  // Streaming robustness - runId + abort tracking
  currentRunId: string | null;
  abortController: AbortController | null;

  // Trip input selectors (computed from document)
  hasAllRequiredFields: () => boolean;

  // Trip input actions
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

  // Set document from graph plan response (when /v1/graph_plan returns new document)
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
  /** Start a new generation run - returns AbortController for the caller */
  startGeneration: (runId: string) => AbortController;
  /** Abort the current generation (if any) */
  abortGeneration: () => void;
  /** Check if a runId is the current run (ignore late events from stale runs) */
  isCurrentRun: (runId: string) => boolean;

  // Reset
  reset: () => void;
};

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
  // View navigation
  activeView: 'setup' as const,
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
  // Note: Per YC demo spec, only destination is required to generate a plan
  // Other fields (origin, dates) are optional accelerators, not blockers
  hasAllRequiredFields: () => {
    const { document } = get();
    const tripInputs = document?.trip_inputs;

    // Require destination
    const hasDestination = Boolean(tripInputs?.destination);

    // Dates are "set" if either:
    // 1. Explicit start_date && end_date
    // 2. OR date_flex with a planning window (duration or date range)
    const hasExplicitDates = Boolean(tripInputs?.start_date && tripInputs?.end_date);
    const hasFlexibleDates = Boolean(
      tripInputs?.date_flex &&
      (tripInputs?.trip_duration || tripInputs?.date_window_start)
    );
    const hasDates = hasExplicitDates || hasFlexibleDates;

    // Per YC demo spec: destination + dates (or flexible dates) required
    return hasDestination && hasDates;
  },

  // Trip input actions
  commitTripInputs: async (updates: DocumentTripInputsPatch): Promise<boolean> => {
    const { document, version, isCommitting } = get();

    // Prevent concurrent commits - if already committing, skip this request
    if (isCommitting) {
      return false;
    }

    // If no document exists yet, we can't commit trip inputs
    // The document is created by the backend when the first chat message is sent
    if (!document) {
      if (process.env.NODE_ENV !== 'production') {
        console.warn('commitTripInputs called but no document exists yet');
      }
      return false;
    }

    // Mark as committing to prevent concurrent requests
    set({ isCommitting: true });

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

      const res = await apiFetch('/v1/document', {
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
          const freshRes = await apiFetch('/v1/document');
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

      // Non-409 error - rollback
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
  },

  fetchDocument: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/v1/document');
      if (!res.ok) {
        if (res.status === 204 || res.status === 404) {
          // 204: No document yet (expected for new sessions)
          // 404: Legacy handling
          set({ isLoading: false, document: null });
          return null;
        }
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      // DEBUG: Log tiles from fetchDocument
      console.log('[documentStore.fetchDocument] Response tiles:', {
        tilesCount: Object.keys(response.document.tiles ?? {}).length,
        tilesKeys: Object.keys(response.document.tiles ?? {}),
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
      });
      return response.document;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch document';
      set({ isLoading: false, error: message });
      return null;
    }
  },

  patchDocument: async (patch: PlanDocumentPatch) => {
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/v1/document', {
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

    // DEBUG: Log document state when setting
    console.log('[documentStore] setFromPlanResponse:', {
      strategy_sections_count: response.document.strategy_sections?.length ?? 0,
      strategy_sections: response.document.strategy_sections,
      plan_view_state: response.document.plan_view_state,
      executed_strategy_topics: response.document.executed_strategy_topics,
      tiles_count: Object.keys(response.document.tiles ?? {}).length,
      tiles_keys: Object.keys(response.document.tiles ?? {}),
    });

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

    set({
      version: response.version,
      updatedBy: response.updated_by,
      updatedAt: response.updated_at,
      document: response.document,
      selectedBranchId:
        get().selectedBranchId ||
        primaryBranch?.id ||
        response.document.branches[0]?.id ||
        null,
      llmUpdatedFields: newLLMUpdatedFields,
    });
  },

  mergeEnvelope: (envelope: Partial<PlanDocumentData>) => {
    const { document: currentDoc } = get();
    if (!currentDoc) return;

    // DEBUG: Log what's in the envelope
    console.log('[documentStore.mergeEnvelope] Received envelope:', {
      hasTiles: envelope.tiles !== undefined,
      tilesKeys: envelope.tiles ? Object.keys(envelope.tiles) : [],
      tilesCount: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      plan_view_state: envelope.plan_view_state,
      envelopeKeys: Object.keys(envelope),
    });

    // Merge envelope fields into current document
    // Only update fields that are present in the envelope
    const updatedDoc: PlanDocumentData = {
      ...currentDoc,
      // Plan view state fields
      ...(envelope.plan_view_state !== undefined && { plan_view_state: envelope.plan_view_state }),
      ...(envelope.strategy_sections !== undefined && { strategy_sections: envelope.strategy_sections }),
      ...(envelope.open_decisions !== undefined && { open_decisions: envelope.open_decisions }),
      ...(envelope.itinerary_overview !== undefined && { itinerary_overview: envelope.itinerary_overview }),
      ...(envelope.day_cards !== undefined && { day_cards: envelope.day_cards }),
      ...(envelope.itinerary_assumptions !== undefined && { itinerary_assumptions: envelope.itinerary_assumptions }),
      ...(envelope.needs_refresh !== undefined && { needs_refresh: envelope.needs_refresh }),
      ...(envelope.can_expand_to_itinerary !== undefined && { can_expand_to_itinerary: envelope.can_expand_to_itinerary }),
      // Generation state
      ...(envelope.generation !== undefined && { generation: envelope.generation }),
      // Tiles (if included in envelope)
      ...(envelope.tiles !== undefined && { tiles: envelope.tiles }),
    };

    // DEBUG: Log what ended up in document.tiles after merge
    console.log('[documentStore.mergeEnvelope] After merge - document.tiles:', {
      tilesKeys: Object.keys(updatedDoc.tiles ?? {}),
      tilesCount: Object.keys(updatedDoc.tiles ?? {}).length,
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
    // Abort any existing generation first
    const { abortController: existingController } = get();
    if (existingController) {
      existingController.abort();
    }

    // Create new controller for this run
    const controller = new AbortController();
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
  setActiveView: (view: 'setup' | 'plan' | 'book') => {
    set({ activeView: view });
  },

  reset: () => {
    // Abort any in-flight generation on reset
    const { abortController } = get();
    if (abortController) {
      abortController.abort();
    }
    set({ ...initialState, llmUpdatedFields: new Set(), activeView: 'setup' });
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
