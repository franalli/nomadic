/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * Centralized state store for PlanDocument using Zustand.
 * This is the single source of truth for branches and tiles in the frontend.
 */

import { create } from 'zustand';
import { useShallow } from 'zustand/react/shallow';

import { apiFetch } from '@/lib/api';
import { debugLog } from '@/lib/debug';
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
import type { DayCard, GenerationState, StrategySection } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

type EnvelopeUpdate = Partial<PlanDocumentData> & { generation?: GenerationState };

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

const DEFAULT_FLIGHT_SETTINGS: FlightSettings = {
  round_trip: true,
  cabin_class: 'economy',
  direct_only: false,
};

const DEFAULT_HOTEL_SETTINGS: HotelSettings = {
  min_stars: 0,
  amenities: [],
};

const DEFAULT_ACTIVITY_SETTINGS: ActivitySettings = {
  categories: [],
  skill_level: null,
};

const DEFAULT_TRANSPORT_SETTINGS: TransportSettings = {
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
type LLMUpdatableField =
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
// View State Ordering (for downgrade protection)
// ─────────────────────────────────────────────────────────────────────────────
// IMPORTANT: All states from backend must be mapped here for downgrade protection to work!
// Backend states: S0_BOOTSTRAP, S1_FRAMING, S2_STRATEGY_READY, S2_BLOCKED, S3_ITINERARY_READY, S3_EDITING, S3_BLOCKED
// Frontend also uses: S0_EMPTY (reset), S1_DESTINATION_SET, S3_PARTIAL_CONFLICT
const VIEW_STATE_ORDER: Record<string, number> = {
  // Stage 0 - Bootstrap/Setup
  S0_EMPTY: 0,
  S0_BOOTSTRAP: 0,
  // Stage 1 - Framing
  S1_DESTINATION_SET: 1,
  S1_FRAMING: 1,
  // Stage 2 - Strategy
  S2_BLOCKED: 1.5,  // Blocked is less than ready
  S2_STRATEGY_READY: 2,
  // Stage 3 - Itinerary
  S3_BLOCKED: 2.5,
  S3_EDITING: 2.5,
  S3_PARTIAL_CONFLICT: 2.5,  // Conflict state (has partial day_cards)
  S3_ITINERARY_READY: 3,
};

const isS3ViewState = (state: string | null | undefined): boolean => Boolean(state?.startsWith('S3_'));

function shouldBlockViewStateDowngrade(
  prevViewState: string | null | undefined,
  nextViewState: string | null | undefined,
  hasDayCards: boolean
): boolean {
  if (!hasDayCards || !nextViewState || nextViewState === 'S0_EMPTY') {
    return false;
  }

  // Lateral transitions inside Stage 3 are valid (e.g. READY -> EDITING on conflicts).
  if (isS3ViewState(prevViewState) && isS3ViewState(nextViewState)) {
    return false;
  }

  const prevOrder = VIEW_STATE_ORDER[prevViewState ?? 'S0_EMPTY'] ?? 0;
  const nextOrder = VIEW_STATE_ORDER[nextViewState] ?? 0;
  return nextOrder < prevOrder;
}

// ─────────────────────────────────────────────────────────────────────────────
// Image URL Hygiene (no Picsum hosts)
// ─────────────────────────────────────────────────────────────────────────────
const BLOCKED_IMAGE_HOSTS = new Set(['picsum.photos', 'fastly.picsum.photos']);
const UNSPLASH_FALLBACK_IMAGE =
  'https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1200&h=800&fit=crop&auto=format';

function sanitizeImageUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;

  try {
    const hostname = new URL(url).hostname.toLowerCase();
    if (BLOCKED_IMAGE_HOSTS.has(hostname) || hostname.endsWith('.picsum.photos')) {
      return undefined;
    }
    return url;
  } catch {
    // Best-effort fallback for malformed URLs.
    return url.includes('picsum.photos') ? undefined : url;
  }
}

function sanitizeRequiredImageUrl(url: string | null | undefined): string {
  return sanitizeImageUrl(url) ?? UNSPLASH_FALLBACK_IMAGE;
}

function sanitizeTiles(tiles: Record<string, Tile> | undefined): Record<string, Tile> | undefined {
  if (!tiles) return tiles;

  let changed = false;
  const sanitized: Record<string, Tile> = {};
  for (const [tileId, tile] of Object.entries(tiles)) {
    const imageUrl = sanitizeImageUrl(tile.image_url);
    if (imageUrl !== tile.image_url) {
      changed = true;
      sanitized[tileId] = { ...tile, image_url: imageUrl };
    } else {
      sanitized[tileId] = tile;
    }
  }

  return changed ? sanitized : tiles;
}

function sanitizeDayCards(dayCards: DayCard[] | undefined): DayCard[] | undefined {
  if (!dayCards) return dayCards;

  let changed = false;
  const sanitized = dayCards.map((card) => {
    let cardChanged = false;
    const blocks = card.blocks.map((block) => {
      let blockChanged = false;
      const imageUrl = sanitizeImageUrl(block.image_url);

      let bookedTile = block.booked_tile;
      if (bookedTile) {
        const bookedTileImage = sanitizeImageUrl(bookedTile.image_url);
        if (bookedTileImage !== bookedTile.image_url) {
          blockChanged = true;
          bookedTile = { ...bookedTile, image_url: bookedTileImage };
        }
      }

      if (imageUrl !== block.image_url) {
        blockChanged = true;
      }

      if (!blockChanged) return block;
      cardChanged = true;
      return {
        ...block,
        image_url: imageUrl,
        booked_tile: bookedTile,
      };
    });

    if (!cardChanged) return card;
    changed = true;
    return { ...card, blocks };
  });

  return changed ? sanitized : dayCards;
}

function sanitizeStrategySections(
  strategySections: StrategySection[] | undefined
): StrategySection[] | undefined {
  if (!strategySections) return strategySections;

  let changed = false;
  const sanitized = strategySections.map((section) => {
    let sectionChanged = false;

    const heroImage = sanitizeImageUrl(section.hero_image);
    if (heroImage !== section.hero_image) {
      sectionChanged = true;
    }

    const contentAdded = section.content_added?.map((item) => {
      const imageUrl = sanitizeImageUrl(item.image_url);
      if (imageUrl !== item.image_url) {
        sectionChanged = true;
        return { ...item, image_url: imageUrl };
      }
      return item;
    });

    const destinationGallery = section.destination_gallery?.map((item) => {
      const imageUrl = sanitizeRequiredImageUrl(item.image_url);
      if (imageUrl !== item.image_url) {
        sectionChanged = true;
        return { ...item, image_url: imageUrl };
      }
      return item;
    });

    const vibeTrio = section.vibe_trio?.map((item) => {
      const imageUrl = sanitizeRequiredImageUrl(item.image_url);
      if (imageUrl !== item.image_url) {
        sectionChanged = true;
        return { ...item, image_url: imageUrl };
      }
      return item;
    });

    if (!sectionChanged) return section;
    changed = true;
    return {
      ...section,
      hero_image: heroImage,
      content_added: contentAdded,
      destination_gallery: destinationGallery,
      vibe_trio: vibeTrio,
    };
  });

  return changed ? sanitized : strategySections;
}

function sanitizeDocumentImages(document: PlanDocumentData): PlanDocumentData {
  const destinationCard = (() => {
    if (!document.destination_card) return document.destination_card;
    const imageUrl = sanitizeImageUrl(document.destination_card.image_url);
    if (imageUrl === document.destination_card.image_url) {
      return document.destination_card;
    }
    return {
      ...document.destination_card,
      image_url: imageUrl,
    };
  })();
  const tiles = sanitizeTiles(document.tiles);
  const dayCards = sanitizeDayCards(document.day_cards);
  const strategySections = sanitizeStrategySections(document.strategy_sections);

  const changed =
    destinationCard !== document.destination_card ||
    tiles !== document.tiles ||
    dayCards !== document.day_cards ||
    strategySections !== document.strategy_sections;

  if (!changed) return document;

  return {
    ...document,
    destination_card: destinationCard,
    tiles: tiles ?? {},
    day_cards: dayCards,
    strategy_sections: strategySections,
  };
}

function sanitizeEnvelopeImages(envelope: Partial<PlanDocumentData>): Partial<PlanDocumentData> {
  let changed = false;
  const sanitized: Partial<PlanDocumentData> = { ...envelope };

  if (envelope.destination_card !== undefined) {
    const destinationCard = (() => {
      if (!envelope.destination_card) return envelope.destination_card;
      const imageUrl = sanitizeImageUrl(envelope.destination_card.image_url);
      if (imageUrl === envelope.destination_card.image_url) {
        return envelope.destination_card;
      }
      return {
        ...envelope.destination_card,
        image_url: imageUrl,
      };
    })();
    if (destinationCard !== envelope.destination_card) {
      changed = true;
      sanitized.destination_card = destinationCard;
    }
  }

  if (envelope.tiles !== undefined) {
    const tiles = sanitizeTiles(envelope.tiles);
    if (tiles !== envelope.tiles) {
      changed = true;
      sanitized.tiles = tiles;
    }
  }

  if (envelope.day_cards !== undefined) {
    const dayCards = sanitizeDayCards(envelope.day_cards);
    if (dayCards !== envelope.day_cards) {
      changed = true;
      sanitized.day_cards = dayCards;
    }
  }

  if (envelope.strategy_sections !== undefined) {
    const strategySections = sanitizeStrategySections(envelope.strategy_sections);
    if (strategySections !== envelope.strategy_sections) {
      changed = true;
      sanitized.strategy_sections = strategySections;
    }
  }

  return changed ? sanitized : envelope;
}

// ─────────────────────────────────────────────────────────────────────────────
// User-Dirty Settings Tracker
// ─────────────────────────────────────────────────────────────────────────────
// Tracks which settings the user has explicitly modified via the UI (pills/sheets).
// ensureSettingsFlushed only sends dirty settings, preventing empty defaults from
// overwriting backend-derived values (e.g., specialist-extracted categories).
// Module-level (not Zustand state) to avoid unnecessary re-renders.
const _userDirtySettings = new Set<string>();

export function markSettingDirty(key: string) {
  _userDirtySettings.add(key);
}

type EnsureSettingsFlushOptions = {
  requestId?: string;
  sendCycleId?: string;
};

const DIRTY_SETTING_KEYS = [
  'activity_settings',
  'hotel_settings',
  'flight_settings',
  'transport_settings',
  'booking_types',
] as const;

const _flushHashBySendCycle = new Map<string, string>();
const MAX_TRACKED_SEND_CYCLES = 32;

function _flushPayloadHash(payload: Partial<DocumentTripInputsPatch>): string {
  // Payload keys are inserted deterministically in ensureSettingsFlushed.
  return JSON.stringify(payload);
}

function _rememberFlushHash(sendCycleId: string, hash: string): boolean {
  const existing = _flushHashBySendCycle.get(sendCycleId);
  if (existing === hash) return false;
  _flushHashBySendCycle.set(sendCycleId, hash);
  if (_flushHashBySendCycle.size > MAX_TRACKED_SEND_CYCLES) {
    const oldest = _flushHashBySendCycle.keys().next().value as string | undefined;
    if (oldest) {
      _flushHashBySendCycle.delete(oldest);
    }
  }
  return true;
}

function _clearFlushHash(sendCycleId?: string): void {
  if (!sendCycleId) return;
  _flushHashBySendCycle.delete(sendCycleId);
}

function clearDirtySettingsForUpdates(updates: Partial<DocumentTripInputsPatch>): void {
  for (const key of DIRTY_SETTING_KEYS) {
    if (key in updates) {
      _userDirtySettings.delete(key);
    }
  }
}

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

// Debounce timer for preference PATCHes — batches rapid heart toggles into a single PATCH
let preferencePatchTimer: ReturnType<typeof setTimeout> | null = null;

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

  // Expand-itinerary mutex (prevents cascade between auto-expand and preference regen)
  expandInProgress: boolean;
  setExpandInProgress: (inProgress: boolean) => void;

  // Fill-day per-day mutex (prevents concurrent fill-day calls on the same day)
  _fillingDays: Set<number>;
  claimFillDay: (day: number) => boolean;
  releaseFillDay: (day: number) => void;

  // General mutation mutex (blocks graph calls while fill-day/drag-drop in-flight)
  _pendingMutations: number;
  claimMutation: () => void;
  releaseMutation: () => void;
  hasPendingMutations: () => boolean;

  // Cart state (for BOOKING mode)
  cartTileIds: Set<string>;
  addToCart: (tileId: string) => void;
  removeFromCart: (tileId: string) => void;
  clearCart: () => void;

  // LLM update tracking - fields that were recently updated by the planner
  llmUpdatedFields: Set<LLMUpdatableField>;

  // Envelope-driven generation status (store-owned, not persisted in document)
  generation: GenerationState | null;

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
  /** Flush all user-owned settings to backend. Call before graph runs to prevent race conditions. */
  ensureSettingsFlushed: (options?: EnsureSettingsFlushOptions) => Promise<void>;

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
  mergeEnvelope: (envelope: EnvelopeUpdate) => void;

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
  /** Complete the current generation - clears runId to allow re-entry */
  completeGeneration: () => void;
  /** Check if a runId is the current run (ignore late events from stale runs) */
  isCurrentRun: (runId: string) => boolean;

  // Fill-day: surgical single day card replacement + atomic tile merge
  replaceDayCard: (dayNumber: number, newCard: DayCard, newVersion?: number, newTiles?: Record<string, Tile>) => void;

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
  // Expand-itinerary mutex
  expandInProgress: false,
  // Fill-day per-day mutex
  _fillingDays: new Set<number>(),
  // General mutation mutex
  _pendingMutations: 0,
  // Cart state
  cartTileIds: new Set<string>(),
  // Envelope-driven generation status (not persisted in document payload)
  generation: null as GenerationState | null,
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

function filterNoopTripInputPatch(
  currentInputs: DocumentTripInputs | undefined,
  updates: DocumentTripInputsPatch
): DocumentTripInputsPatch {
  if (!currentInputs) return updates;

  const filtered: DocumentTripInputsPatch = {};

  for (const [key, nextValue] of Object.entries(updates)) {
    if (nextValue === undefined) continue;
    const typedKey = key as keyof DocumentTripInputsPatch;
    const currentValue = currentInputs[typedKey as keyof DocumentTripInputs];

    let isSame = false;
    if (
      typeof nextValue === 'object' &&
      nextValue !== null &&
      typeof currentValue === 'object' &&
      currentValue !== null
    ) {
      isSame = shallowObjectEqual(
        nextValue as Record<string, unknown>,
        currentValue as Record<string, unknown>
      );
    } else {
      isSame = currentValue === nextValue;
    }

    if (!isSame) {
      (filtered as Record<string, unknown>)[key] = nextValue;
    }
  }

  return filtered;
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
    debugLog('[documentStore] 🔄 updateTripInputs CALLED with:', updates);
    let { document } = get();
    if (!document) {
      // Create minimal document so pill settings are stored before first graph run.
      // commitTripInputs uses the same pattern (lines 582-594).
      document = {
        trip_context_id: null,
        trip_inputs: { ...DEFAULT_TRIP_INPUTS },
        branches: [],
        tiles: {},
        plan_view_state: 'S0_BOOTSTRAP' as const,
      };
      set({ document, version: 0 });
    }

    const previousDestination = document.trip_inputs?.destination;
    const newDestination = updates.destination;

    // Log destination change for debugging (tiles cleared by backend on GENERATE_PLAN_NOW)
    if (newDestination && newDestination !== previousDestination) {
      debugLog('[documentStore] 📍 Destination changed (tiles kept until Refresh):', {
        from: previousDestination,
        to: newDestination,
      });

      // Clear stale preferences from old destination
      set({ preferredTileIds: new Set() });
      debugLog('[documentStore] 🧹 Cleared preferredTileIds (destination changed)');
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
    debugLog('[documentStore] 📝 Trip inputs updated (sync):', {
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

    const effectiveUpdates = filterNoopTripInputPatch(document.trip_inputs, updates);
    if (Object.keys(effectiveUpdates).length === 0) {
      debugLog('[documentStore] ⏭️ commitTripInputs SKIP (no-op patch)', updates);
      debugLog('[VERIFY][PATCH_DEDUPE] no-op commit skipped', {
        attemptedFields: Object.keys(updates),
        version,
      });
      clearDirtySettingsForUpdates(updates);
      releaseCommitLock();
      return true;
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
        ...effectiveUpdates,
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
          trip_inputs: effectiveUpdates,
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

        // Settings included in this successful PATCH no longer need pre-graph flush.
        clearDirtySettingsForUpdates(effectiveUpdates);

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

            // Settings included in this successful retry no longer need pre-graph flush.
            clearDirtySettingsForUpdates(effectiveUpdates);

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

  ensureSettingsFlushed: async (options?: EnsureSettingsFlushOptions) => {
    const requestId = options?.requestId ?? null;
    const sendCycleId = options?.sendCycleId;
    debugLog('[ensureSettingsFlushed] START', {
      request_id: requestId,
      send_cycle_id: sendCycleId,
    });
    // Wait for any in-flight commit to complete
    if (_commitLock) {
      debugLog('[ensureSettingsFlushed] waiting for _commitLock...', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
      });
      await _commitLock;
    }

    const doc = get().document;
    if (!doc?.trip_inputs) {
      debugLog('[ensureSettingsFlushed] BAIL — no document or trip_inputs in zustand', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
      });
      return;
    }

    // Only flush settings the user explicitly changed via the UI.
    // Prevents overwriting backend-derived values (e.g., specialist-extracted
    // categories like ["diving", "hiking"]) with empty frontend defaults.
    const dirty = new Set(_userDirtySettings);

    if (dirty.size === 0) {
      debugLog('[ensureSettingsFlushed] SKIP — no dirty settings', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
      });
      return;
    }

    const ti = doc.trip_inputs;
    const payload: Partial<DocumentTripInputsPatch> = {};
    if (dirty.has('activity_settings')) payload.activity_settings = ti.activity_settings;
    if (dirty.has('hotel_settings')) payload.hotel_settings = ti.hotel_settings;
    if (dirty.has('flight_settings')) payload.flight_settings = ti.flight_settings;
    if (dirty.has('transport_settings')) payload.transport_settings = ti.transport_settings;
    if (dirty.has('booking_types')) payload.booking_types = ti.booking_types;

    const payloadKeys = Object.keys(payload);
    if (payloadKeys.length === 0) {
      debugLog('[ensureSettingsFlushed] SKIP — empty flush payload', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
        dirty: [...dirty],
      });
      debugLog('[VERIFY][PATCH_DEDUPE] hash=empty skipped', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
      });
      return;
    }

    const payloadHash = _flushPayloadHash(payload);
    if (sendCycleId && !_rememberFlushHash(sendCycleId, payloadHash)) {
      debugLog('[ensureSettingsFlushed] SKIP — duplicate payload in send cycle', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
        hash: payloadHash,
      });
      debugLog(`[VERIFY][PATCH_DEDUPE] hash=${payloadHash} skipped request_id=${requestId}`);
      return;
    }

    debugLog('[ensureSettingsFlushed] FLUSHING dirty settings:', {
      request_id: requestId,
      send_cycle_id: sendCycleId,
      dirty: [...dirty],
      payload_keys: payloadKeys,
      payload_hash: payloadHash,
    });
    const committed = await get().commitTripInputs(payload);
    if (committed) {
      clearDirtySettingsForUpdates(payload);
      debugLog('[ensureSettingsFlushed] DONE — settings synced before graph', {
        request_id: requestId,
        send_cycle_id: sendCycleId,
      });
      debugLog(`[VERIFY][PATCH_DEDUPE] hash=${payloadHash} committed request_id=${requestId}`);
      return;
    }
    _clearFlushHash(sendCycleId);
    debugLog('[ensureSettingsFlushed] RETAIN — commit failed, dirty settings kept', {
      request_id: requestId,
      send_cycle_id: sendCycleId,
    });
    debugLog(`[VERIFY][PATCH_DEDUPE] hash=${payloadHash} retained request_id=${requestId}`);
  },

  fetchDocument: async () => {
    debugLog('[documentStore.fetchDocument] 🚀 Starting fetch...');
    set({ isLoading: true, error: null });
    try {
      const res = await apiFetch('/api/document');
      debugLog('[documentStore.fetchDocument] 📡 Response status:', res.status);

      // Handle 204 No Content FIRST (before trying to parse JSON)
      // 204 is a success status (res.ok=true) but has no body
      if (res.status === 204) {
        debugLog('[documentStore.fetchDocument] ⚠️ No document (204 No Content)');
        set({ isLoading: false, document: null });
        return null;
      }

      if (!res.ok) {
        if (res.status === 404) {
          // 404: Legacy handling for no document
          debugLog('[documentStore.fetchDocument] ⚠️ No document (404)');
          set({ isLoading: false, document: null });
          return null;
        }
        throw new Error(`${res.status}`);
      }
      const response: PlanDocumentResponse = await res.json();
      const sanitizedResponseDocument = sanitizeDocumentImages(response.document);
      // DEBUG: Log document details
      debugLog('[documentStore.fetchDocument] Response:', {
        tilesCount: Object.keys(sanitizedResponseDocument.tiles ?? {}).length,
        preferredTileIds: sanitizedResponseDocument.preferred_tile_ids,
        branchesCount: sanitizedResponseDocument.branches?.length ?? 0,
        plan_view_state: sanitizedResponseDocument.plan_view_state,
        dayCardsCount: sanitizedResponseDocument.day_cards?.length ?? 0,
      });

      // ============================================================
      // VIEW STATE UPWARD RECONCILIATION (stale DB state repair)
      // ============================================================
      // If the backend persisted a stale plan_view_state that contradicts
      // the actual data present, promote it. Guards against lateral/blocked
      // states that should not be overridden.
      const fetchedViewState = sanitizedResponseDocument.plan_view_state;
      const fetchedDayCards = sanitizedResponseDocument.day_cards ?? [];
      const fetchedViolations = sanitizedResponseDocument.constraint_violations ?? [];
      const fetchedSections = sanitizedResponseDocument.strategy_sections ?? [];
      let reconciledViewState = fetchedViewState;

      // Day cards promotion: only from states below S3 that aren't already S3 variants
      // S3_BLOCKED, S3_EDITING, S3_PARTIAL_CONFLICT are lateral S3 states — don't override
      const isAlreadyS3 = fetchedViewState?.startsWith('S3_');
      if (
        fetchedDayCards.length > 0 &&
        !isAlreadyS3 &&
        !fetchedViewState?.includes('BLOCKED') &&
        (VIEW_STATE_ORDER[fetchedViewState ?? 'S0_EMPTY'] ?? 0) < VIEW_STATE_ORDER['S3_ITINERARY_READY']
      ) {
        const promotedState = fetchedViolations.length > 0 ? 'S3_EDITING' : 'S3_ITINERARY_READY';
        reconciledViewState = promotedState;
        debugLog(
          `[documentStore.fetchDocument] 🔧 Reconciled stale view state: ${fetchedViewState} → ${promotedState} (${fetchedDayCards.length} day_cards, ${fetchedViolations.length} violations)`
        );
      }

      // Strategy sections promotion: only from states below S2, skip BLOCKED
      if (
        reconciledViewState === fetchedViewState && // no day_cards promotion happened
        fetchedSections.length > 0 &&
        !fetchedViewState?.includes('BLOCKED') &&
        (VIEW_STATE_ORDER[fetchedViewState ?? 'S0_EMPTY'] ?? 0) < VIEW_STATE_ORDER['S2_STRATEGY_READY']
      ) {
        reconciledViewState = 'S2_STRATEGY_READY';
        debugLog(
          `[documentStore.fetchDocument] 🔧 Reconciled stale view state: ${fetchedViewState} → S2_STRATEGY_READY (${fetchedSections.length} strategy_sections exist)`
        );
      }

      const documentToStore = reconciledViewState !== fetchedViewState
        ? {
            ...sanitizedResponseDocument,
            plan_view_state: reconciledViewState as typeof fetchedViewState,
          }
        : sanitizedResponseDocument;

      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: documentToStore,
        isLoading: false,
        // Auto-select primary branch if none selected
        selectedBranchId:
          get().selectedBranchId ||
          sanitizedResponseDocument.branches.find((b) => b.is_primary)?.id ||
          sanitizedResponseDocument.branches[0]?.id ||
          null,
        // Hydrate preferences from DB (replaces sessionStorage)
        preferredTileIds: new Set(sanitizedResponseDocument.preferred_tile_ids ?? []),
      });
      return sanitizedResponseDocument;
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
      // Frontend-only: plan_view_state, strategy_sections, tiles, etc.
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
        open_decisions: currentDoc?.open_decisions ?? response.document.open_decisions,
      };

      set({
        version: response.version,
        updatedBy: response.updated_by,
        updatedAt: response.updated_at,
        document: sanitizeDocumentImages(mergedDocument),
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
    debugLog(
      `[documentStore.setFromPlanResponse] 🏷️ Writing suggestions:`,
      `received=${response.document.suggested_responses?.length ?? 0}`,
      `values=${JSON.stringify(response.document.suggested_responses)}`,
      `chips=${response.document.suggestion_chips?.length ?? 0}`
    );

    // Safety net: map legacy itinerary_day_cards → day_cards if present
    const rawDoc = response.document as PlanDocumentData & { itinerary_day_cards?: DayCard[] };
    if (rawDoc.itinerary_day_cards && !rawDoc.day_cards) {
      rawDoc.day_cards = rawDoc.itinerary_day_cards;
      debugLog(`[documentStore.setFromPlanResponse] 📅 Mapped itinerary_day_cards → day_cards (${rawDoc.day_cards.length} cards)`);
    }

    // Normalize inbound image URLs across destination_card, tiles, day_cards, strategy sections.
    response.document = sanitizeDocumentImages(rawDoc);
    if (response.document.day_cards?.length) {
      debugLog(`[documentStore.setFromPlanResponse] 📅 SSE day_cards: ${response.document.day_cards.length} cards`);
    }

    const { document: currentDoc, llmUpdatedFields } = get();
    const primaryBranch = response.document.branches.find((b) => b.is_primary);

    // ============================================================
    // DESTINATION LOCK: Once set, destination can only change via full trip reset
    // ============================================================
    const currentDestination = currentDoc?.trip_inputs?.destination;
    const incomingDestination = response.document.trip_inputs?.destination;

    if (currentDestination && incomingDestination &&
        currentDestination.toLowerCase().trim() !== incomingDestination.toLowerCase().trim()) {
      debugLog(
        `[documentStore.setFromPlanResponse] 🔒 BLOCKED destination change: "${currentDestination}" → "${incomingDestination}" (destination locked once set)`
      );
      // Preserve current destination in the response
      response.document.trip_inputs.destination = currentDestination;
    }

    // ============================================================
    // DESTINATION CHANGE DETECTION (now should never trigger due to lock above)
    // ============================================================
    const prevDestination = currentDoc?.trip_inputs?.destination?.toLowerCase().trim();
    const newDestination = response.document.trip_inputs?.destination?.toLowerCase().trim();
    const destinationChanged = prevDestination && newDestination && prevDestination !== newDestination;

    if (destinationChanged) {
      debugLog(
        `[documentStore.setFromPlanResponse] 🌍 Destination changed: "${prevDestination}" → "${newDestination}"`
      );
      // Clear chat messages on destination change

      const { useChatStore } = require('./chatStore');
      useChatStore.getState().resetChat();
      debugLog('[documentStore.setFromPlanResponse] 💬 Chat: CLEARED (destination changed)');
    }

    // ============================================================
    // DATE CHANGE DETECTION (triggers strategy section refresh)
    // ============================================================
    const prevStartDate = currentDoc?.trip_inputs?.start_date;
    const prevEndDate = currentDoc?.trip_inputs?.end_date;
    const newStartDate = response.document.trip_inputs?.start_date;
    const newEndDate = response.document.trip_inputs?.end_date;
    const datesChanged = (prevStartDate && newStartDate && prevStartDate !== newStartDate) ||
                         (prevEndDate && newEndDate && prevEndDate !== newEndDate);

    if (datesChanged) {
      debugLog(
        `[documentStore.setFromPlanResponse] 📅 Dates changed: ${prevStartDate}→${prevEndDate} to ${newStartDate}→${newEndDate}`
      );
    }

    // ============================================================
    // VIEW STATE DOWNGRADE PROTECTION
    // ============================================================
    const prevViewState = currentDoc?.plan_view_state;
    const newViewState = response.document.plan_view_state;
    const currentDayCards = currentDoc?.day_cards ?? [];
    const hasDayCards = currentDayCards.length > 0;

    // GUARD: Never downgrade view state when itinerary exists
    // EXCEPTION: S0_EMPTY = genuine RESET intent (user said "start over"), always accept
    const wouldDowngrade = shouldBlockViewStateDowngrade(prevViewState, newViewState, hasDayCards);

    const finalViewState = wouldDowngrade ? prevViewState : newViewState;

    if (wouldDowngrade) {
      debugLog(`[documentStore.setFromPlanResponse] 🛡️ Blocked view state downgrade: ${prevViewState} → ${newViewState} (day_cards exist: ${currentDayCards.length})`);
    }

    // DEBUG: Log document state when setting
    debugLog('[documentStore] setFromPlanResponse:', {
      strategy_sections_count: response.document.strategy_sections?.length ?? 0,
      strategy_sections: response.document.strategy_sections,
      plan_view_state: response.document.plan_view_state,
      executed_strategy_topics: response.document.executed_strategy_topics,
      tiles_count: Object.keys(response.document.tiles ?? {}).length,
      tiles_keys: Object.keys(response.document.tiles ?? {}),
      destinationChanged,
      wouldDowngrade,
      finalViewState,
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
      // Merge activity_settings: preserve user-set day_preferences when backend omits them
      activity_settings: {
        ...localTripInputs?.activity_settings,
        ...responseTripInputs.activity_settings,
        categories: responseTripInputs.activity_settings?.categories
          ?? localTripInputs?.activity_settings?.categories ?? [],
        skill_level: responseTripInputs.activity_settings?.skill_level
          ?? localTripInputs?.activity_settings?.skill_level ?? null,
        day_preferences: responseTripInputs.activity_settings?.day_preferences
          ?? localTripInputs?.activity_settings?.day_preferences,
      },
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
    // FIX: Only create new Set if content actually changed - prevents spurious rebuild triggers
    const currentPreferences = get().preferredTileIds;
    const responsePreferences = response.document.preferred_tile_ids;
    let mergedPreferences = currentPreferences;
    if (responsePreferences && responsePreferences.length > 0) {
      // Check if content actually changed before creating new Set
      const responsePrefSet = new Set(responsePreferences);
      const contentChanged = responsePrefSet.size !== currentPreferences.size ||
        [...responsePrefSet].some(id => !currentPreferences.has(id));
      if (contentChanged) {
        mergedPreferences = responsePrefSet;
      }
    }

    // ============================================================
    // TILE MERGE (conditional on destination, dates, or tiles_replaced flag)
    // ============================================================
    // Merge tiles only for same destination (additive like flights)
    // Full replace on destination change, date change, or backend tiles_replaced flag
    const tilesReplaced = response.document.tiles_replaced === true;
    const mergedTiles = (destinationChanged || datesChanged || tilesReplaced)
      ? response.document.tiles
      : { ...currentDoc?.tiles, ...response.document.tiles };

    if (tilesReplaced) {
      debugLog('[documentStore.setFromPlanResponse] 🔄 Tiles: REPLACED (tiles_replaced flag)');
    }

    // ============================================================
    // DAY CARDS — graph-sent cards always win
    // ============================================================
    // The graph builds day_cards on every turn via ItineraryBuilder.
    // Graph is the authority — always use its cards when present.
    // Only preserve existing cards when graph sent nothing (lightweight routes).
    const graphSentCards = response.document.day_cards;
    const hasGraphSentCards = graphSentCards && graphSentCards.length > 0;
    const finalDayCards = hasGraphSentCards
      ? graphSentCards
      : (datesChanged ? [] : (currentDayCards ?? []));

    if (hasGraphSentCards) {
      debugLog(`[documentStore.setFromPlanResponse] 📅 Day cards: FROM GRAPH (${graphSentCards.length} cards)`);
    } else if (datesChanged) {
      debugLog('[documentStore.setFromPlanResponse] 📅 Day cards: CLEARED (dates changed, no graph cards)');
    } else if (hasDayCards) {
      debugLog(`[documentStore.setFromPlanResponse] 📅 Day cards: PRESERVED (no graph cards, keeping ${currentDayCards.length} existing)`);
    }

    // ============================================================
    // STRATEGY SECTIONS MERGE (preserve content_added, add new specialists)
    // ============================================================
    // When same destination: merge response sections with existing content_added
    // Backend lightweight routes (origin change, settings) don't re-run specialists
    // so response.strategy_sections may lack content_added data
    // BUT new specialists (e.g., "hiking too") MUST be added from response
    const currentSections = currentDoc?.strategy_sections ?? [];
    const responseSections = response.document.strategy_sections ?? [];

    const mergedSections = (() => {
      // Full replacement on destination OR date change (specialists re-run with new activity counts)
      if (destinationChanged || datesChanged) return responseSections;
      if (responseSections.length === 0) return currentSections;

      // Build maps for both current and response sections
      const currentByType = new Map(
        currentSections.map(s => [s.specialist_type, s])
      );
      const responseByType = new Map(
        responseSections.map(s => [s.specialist_type, s])
      );

      // Start with response sections, preserving content_added from current where missing
      const merged = responseSections.map(respSection => {
        const existing = currentByType.get(respSection.specialist_type);
        // If response lacks content_added but we have it cached, preserve it
        if (existing?.content_added && !respSection.content_added) {
          return { ...respSection, content_added: existing.content_added };
        }
        return respSection;
      });

      // Add current sections that aren't in the response (preserve existing specialists)
      for (const current of currentSections) {
        if (!responseByType.has(current.specialist_type)) {
          merged.push(current);
        }
      }

      return merged;
    })();

    if (datesChanged) {
      debugLog(`[documentStore.setFromPlanResponse] 📝 Strategy sections: REPLACED (dates changed, ${responseSections.length} sections)`);
    } else if (!destinationChanged && responseSections.length !== currentSections.length) {
      debugLog(`[documentStore.setFromPlanResponse] 📝 Strategy sections: MERGED (${currentSections.length} → ${mergedSections.length} sections)`);
    } else if (!destinationChanged && currentSections.length > 0) {
      debugLog(`[documentStore.setFromPlanResponse] 📝 Strategy sections: PRESERVED content_added (${mergedSections.length} sections)`);
    }

    set({
      version: response.version,
      updatedBy: response.updated_by,
      updatedAt: response.updated_at,
      document: sanitizeDocumentImages({
        ...response.document,
        plan_view_state: finalViewState,
        tiles: mergedTiles,
        trip_inputs: mergedTripInputs,
        day_cards: finalDayCards,
        strategy_sections: mergedSections,
      }),
      selectedBranchId:
        get().selectedBranchId ||
        primaryBranch?.id ||
        response.document.branches[0]?.id ||
        null,
      llmUpdatedFields: newLLMUpdatedFields,
      preferredTileIds: mergedPreferences,
    });
  },

  mergeEnvelope: (envelope: EnvelopeUpdate) => {
    const { document: currentDoc } = get();
    if (!currentDoc) return;

    envelope = sanitizeEnvelopeImages(envelope);

    // ============================================================
    // DESTINATION LOCK: Once set, destination can only change via full trip reset
    // This prevents LLM from changing destination mid-plan (invalidates all content)
    // ============================================================
    const currentDestination = currentDoc.trip_inputs?.destination;
    const incomingDestination = envelope.trip_inputs?.destination;

    if (currentDestination && incomingDestination &&
        currentDestination.toLowerCase().trim() !== incomingDestination.toLowerCase().trim()) {
      debugLog(
        `[documentStore.mergeEnvelope] 🔒 BLOCKED destination change: "${currentDestination}" → "${incomingDestination}" (destination locked once set)`
      );
      // Strip destination from incoming trip_inputs to preserve current value
      if (envelope.trip_inputs) {
        const restTripInputs = { ...envelope.trip_inputs };
        delete restTripInputs.destination;
        envelope = { ...envelope, trip_inputs: restTripInputs };
      }
    }

    // DEBUG: Log envelope structure for diagnostics
    debugLog('[DEBUG mergeEnvelope] Envelope structure:', {
      has_trip_inputs: !!envelope.trip_inputs,
      trip_inputs_destination: envelope.trip_inputs?.destination,
      has_tiles: !!envelope.tiles,
      tiles_count: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      current_destination: currentDoc.trip_inputs?.destination,
    });

    // DEBUG: Log constraint validation data from envelope
    if (envelope.constraints_validated !== undefined || envelope.constraint_violations !== undefined) {
      debugLog('[DEBUG mergeEnvelope] Constraint data:', {
        constraints_validated: envelope.constraints_validated,
        constraint_violations: envelope.constraint_violations,
      });
    }

    // Detect destination change (now should never happen due to lock above)
    const prevDestination = currentDoc.trip_inputs?.destination?.toLowerCase().trim();
    const newDestination = envelope.trip_inputs?.destination?.toLowerCase().trim();
    const destinationChanged = prevDestination && newDestination && prevDestination !== newDestination;

    if (destinationChanged) {
      debugLog(
        `[documentStore.mergeEnvelope] 🌍 Destination changed: "${prevDestination}" → "${newDestination}"`
      );
      // Clear chat messages on destination change (import chatStore at top of file)

      const { useChatStore } = require('./chatStore');
      useChatStore.getState().resetChat();
      debugLog('[documentStore.mergeEnvelope] 💬 Chat: CLEARED (destination changed)');
    }

    // Detect date changes (for logging/debugging)
    const prevStartDate = currentDoc.trip_inputs?.start_date;
    const prevEndDate = currentDoc.trip_inputs?.end_date;
    const newStartDate = envelope.trip_inputs?.start_date;
    const newEndDate = envelope.trip_inputs?.end_date;
    const datesChanged = (prevStartDate && newStartDate && prevStartDate !== newStartDate) ||
                         (prevEndDate && newEndDate && prevEndDate !== newEndDate);

    if (datesChanged) {
      debugLog(
        `[documentStore.mergeEnvelope] 📅 Dates changed: ${prevStartDate}→${prevEndDate} to ${newStartDate}→${newEndDate}`
      );
    }

    // ============================================================
    // VIEW STATE DOWNGRADE PROTECTION
    // ============================================================
    const prevViewState = currentDoc.plan_view_state;
    const newViewState = envelope.plan_view_state;
    const currentDayCards = currentDoc.day_cards ?? [];
    const hasDayCards = currentDayCards.length > 0;

    // GUARD: Never downgrade view state when itinerary exists
    // EXCEPTION: S0_EMPTY = genuine RESET intent (user said "start over"), always accept
    const wouldDowngrade = shouldBlockViewStateDowngrade(prevViewState, newViewState, hasDayCards);

    const finalViewState = wouldDowngrade ? prevViewState : (newViewState ?? prevViewState);

    if (wouldDowngrade) {
      debugLog(`[documentStore.mergeEnvelope] 🛡️ Blocked view state downgrade: ${prevViewState} → ${newViewState} (day_cards exist: ${currentDayCards.length})`);
    }

    // DEBUG: Log what's in the envelope (including plan_view_state transition)
    debugLog('[documentStore.mergeEnvelope] 📥 Received envelope:', {
      hasTiles: envelope.tiles !== undefined,
      tilesCount: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      hasDayCards,
      dayCardsInEnvelope: envelope.day_cards?.length ?? 0,
      prevViewState,
      newViewState,
      destinationChanged,
      wouldDowngrade,
      finalViewState,
    });

    // Compute tile merge strategy BEFORE building updatedDoc
    let tilesToMerge: Record<string, Tile> | undefined;
    const tilesReplaced = envelope.tiles_replaced === true;

    if (envelope.tiles !== undefined) {
      if (destinationChanged || datesChanged || tilesReplaced) {
        // Full replace: destination changed, dates changed, or backend tiles_replaced flag
        tilesToMerge = envelope.tiles;
        debugLog(`[documentStore.mergeEnvelope] 🔄 Tiles: REPLACED (${destinationChanged ? 'destination changed' : datesChanged ? 'dates changed' : 'tiles_replaced flag'})`);
      } else if (Object.keys(envelope.tiles).length > 0) {
        // Same destination + non-empty: MERGE with existing tiles (additive)
        tilesToMerge = { ...currentDoc.tiles, ...envelope.tiles };
        debugLog('[documentStore.mergeEnvelope] 🔄 Tiles: MERGED (same destination)');
      } else {
        // Same destination + empty: SKIP (preserve existing)
        tilesToMerge = undefined;
        debugLog('[documentStore.mergeEnvelope] ⏭️ Tiles: SKIPPED (empty envelope)');
      }
    }

    // Compute strategy merge strategy (similar to tiles)
    let sectionsToMerge: StrategySection[] | undefined;

    if (envelope.strategy_sections !== undefined) {
      if (destinationChanged) {
        // Destination changed: REPLACE strategy sections (even if empty)
        sectionsToMerge = envelope.strategy_sections;
        debugLog('[documentStore.mergeEnvelope] 📝 Strategy: REPLACED (destination changed)');
      } else {
        // Same destination: merge/update
        sectionsToMerge = envelope.strategy_sections;
        debugLog('[documentStore.mergeEnvelope] 📝 Strategy: MERGED (same destination)');
      }
    }

    // ============================================================
    // DAY CARDS PRESERVE (clear on destination/date change)
    // ============================================================
    let dayCardsToMerge: DayCard[] | undefined;

    if (envelope.day_cards !== undefined) {
      // If day_cards explicitly provided, use them
      dayCardsToMerge = envelope.day_cards;
      debugLog(`[documentStore.mergeEnvelope] 📅 Day Cards: ${envelope.day_cards.length} cards provided`);
    } else if (destinationChanged || datesChanged) {
      // Destination/date changed: CLEAR day_cards
      dayCardsToMerge = [];
      debugLog(
        `[documentStore.mergeEnvelope] 📅 Day Cards: CLEARED (${destinationChanged ? 'destination changed' : 'dates changed'})`
      );
    } else if (hasDayCards) {
      // Preserve existing day_cards when itinerary exists
      dayCardsToMerge = currentDayCards;
      debugLog(`[documentStore.mergeEnvelope] 📅 Day Cards: PRESERVED (itinerary exists: ${currentDayCards.length} cards)`);
    }

    // Merge envelope fields into current document
    const updatedDoc: PlanDocumentData = {
      ...currentDoc,
      // Plan view state fields (use guarded finalViewState)
      ...(finalViewState !== undefined && { plan_view_state: finalViewState }),
      ...(sectionsToMerge !== undefined && { strategy_sections: sectionsToMerge }),
      ...(envelope.open_decisions !== undefined && { open_decisions: envelope.open_decisions }),
      ...(envelope.itinerary_overview !== undefined && { itinerary_overview: envelope.itinerary_overview }),
      ...(dayCardsToMerge !== undefined && { day_cards: dayCardsToMerge }),
      ...(envelope.itinerary_assumptions !== undefined && { itinerary_assumptions: envelope.itinerary_assumptions }),
      ...(envelope.needs_refresh !== undefined && { needs_refresh: envelope.needs_refresh }),
      ...(envelope.can_expand_to_itinerary !== undefined && { can_expand_to_itinerary: envelope.can_expand_to_itinerary }),
      // Tiles: Apply computed merge strategy
      ...(tilesToMerge !== undefined && { tiles: tilesToMerge }),
      // Update trip_inputs if present
      ...(envelope.trip_inputs !== undefined && {
        trip_inputs: { ...currentDoc.trip_inputs, ...envelope.trip_inputs },
      }),
      // Constraint validation receipts for Trip DNA bar badges
      ...(envelope.constraints_validated !== undefined && {
        constraints_validated: envelope.constraints_validated,
      }),
      ...(envelope.constraint_violations !== undefined && {
        constraint_violations: envelope.constraint_violations,
      }),
    };

    // DEBUG: Log final tile state
    debugLog('[documentStore.mergeEnvelope] Final tiles:', {
      previousCount: Object.keys(currentDoc.tiles ?? {}).length,
      envelopeCount: envelope.tiles ? Object.keys(envelope.tiles).length : 0,
      finalCount: Object.keys(updatedDoc.tiles ?? {}).length,
    });

    set({
      document: sanitizeDocumentImages(updatedDoc),
      updatedBy: 'planner',
      updatedAt: new Date().toISOString(),
      generation: envelope.generation !== undefined ? envelope.generation : get().generation,
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
      debugLog('[documentStore] ⚠️ startGeneration REJECTED - already running:', existingRunId);
      return null;
    }

    // Abort any existing (stale) generation
    if (existingController) {
      debugLog('[documentStore] 🔄 Aborting stale controller');
      existingController.abort();
    }

    // Create new controller for this run
    const controller = new AbortController();
    debugLog('[documentStore] ✅ startGeneration ACCEPTED:', runId);
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

  completeGeneration: () => {
    // Clear generation state to allow re-entry (e.g., structural change auto-expand)
    // Unlike abortGeneration, this doesn't abort - just clears the gate
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
    const { preferredTileIds, document } = get();
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

    // Sync to backend — debounce to batch rapid heart toggles into a single PATCH
    if (preferencePatchTimer) clearTimeout(preferencePatchTimer);

    const patchPromise = new Promise<void>((resolve) => {
      preferencePatchTimer = setTimeout(async () => {
        preferencePatchTimer = null;
        const currentSet = get().preferredTileIds;
        const currentVersion = get().version;

        const attemptPatch = async (patchVersion: number): Promise<Response> => {
          const patchData = {
            version: patchVersion,
            preferred_tile_ids: Array.from(currentSet),
          };
          debugLog('[documentStore] 💜 PATCH preferences:', patchData);
          return apiFetch('/api/document', {
            method: 'PATCH',
            body: JSON.stringify(patchData),
          });
        };

        try {
          let res = await attemptPatch(currentVersion);

          // Handle 409 Conflict (version mismatch) - refetch and retry once
          if (res.status === 409) {
            debugLog('[documentStore] Version conflict (409), refetching and retrying...');
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
            debugLog('[documentStore] 💜 PATCH success, new version:', responseData.version);
          } else {
            console.error('[documentStore] 💜 PATCH failed:', res.status);
          }
        } catch (err) {
          console.error('[documentStore] 💜 PATCH error:', err);
        }
        resolve();
      }, 500);
    });

    patchPromise.finally(() => {
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
    const { version, document } = get();
    set({ preferredTileIds: new Set() });

    // Skip backend sync if document doesn't exist (e.g. during session reset)
    if (!document) return;

    // Sync to backend
    const patch = {
      version,
      preferred_tile_ids: [],
    };
    apiFetch('/api/document', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }).catch((err) => {
      console.error('[documentStore] Failed to clear preferences:', err);
    });
  },

  // Regeneration tracking - sync lastGeneratedPreferences after expand-itinerary completes
  markPreferencesAsApplied: () => {
    const { preferredTileIds, lastGeneratedPreferences } = get();

    // Early exit if preferences haven't changed (prevents cascade)
    // Compare by value, not reference, since Sets are always new objects
    if (preferredTileIds.size === lastGeneratedPreferences.size) {
      let allMatch = true;
      for (const id of preferredTileIds) {
        if (!lastGeneratedPreferences.has(id)) {
          allMatch = false;
          break;
        }
      }
      if (allMatch) {
        debugLog('[documentStore] Preferences unchanged, skipping state update');
        return;
      }
    }

    debugLog('[documentStore] Marking preferences as applied:', preferredTileIds.size);
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

  // Expand-itinerary mutex setter
  setExpandInProgress: (inProgress: boolean) => {
    set({ expandInProgress: inProgress });
  },

  // Per-day fill mutex (prevents concurrent fill-day on same day)
  claimFillDay: (day: number): boolean => {
    const { _fillingDays } = get();
    if (_fillingDays.has(day)) return false;
    set({ _fillingDays: new Set([..._fillingDays, day]) });
    return true;
  },
  releaseFillDay: (day: number) => {
    const { _fillingDays } = get();
    const next = new Set(_fillingDays);
    next.delete(day);
    set({ _fillingDays: next });
  },

  // General mutation mutex (blocks graph calls while fill-day/drag-drop in-flight)
  claimMutation: () => {
    set(s => ({ _pendingMutations: s._pendingMutations + 1 }));
  },
  releaseMutation: () => {
    set(s => ({ _pendingMutations: Math.max(0, s._pendingMutations - 1) }));
  },
  hasPendingMutations: () => get()._pendingMutations > 0,

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

  replaceDayCard: (dayNumber, newCard, newVersion, newTiles) => {
    const doc = get().document;
    if (!doc) return;

    const sanitizedCard = sanitizeDayCards([newCard])?.[0] ?? newCard;
    const sanitizedTiles = sanitizeTiles(newTiles);

    set({
      document: {
        ...doc,
        day_cards: (doc.day_cards ?? []).map(dc =>
          dc.day_number === dayNumber ? sanitizedCard : dc
        ),
        tiles: sanitizedTiles
          ? { ...doc.tiles, ...sanitizedTiles }
          : doc.tiles,
      },
      ...(newVersion !== undefined && { version: newVersion }),
    });
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
    _flushHashBySendCycle.clear();
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

// =============================================================================
// Heart Preference System (PLANNING mode - preference signals for AI weighting)
// =============================================================================

/**
 * Check if a specific tile is preferred. Avoids subscribing to the whole Set.
 */
export const useTilePreference = (tileId: string) =>
  useDocumentStore((state) => state.preferredTileIds.has(tileId));

/**
 * Get preference actions. Used for toggling/clearing preferences.
 * Uses useShallow to prevent re-renders when unrelated store state changes.
 */
export const usePreferenceActions = () =>
  useDocumentStore(useShallow((state) => ({
    toggleTilePreference: state.toggleTilePreference,
    clearPreferences: state.clearPreferences,
  })));

/**
 * Hydrate preferences from API response (not sessionStorage).
 * This is now called automatically by fetchDocument and setFromPlanResponse.
 * Kept for backward compatibility but does nothing - preferences come from DB.
 */
export const hydratePreferences = () => {
  // No-op: Preferences are hydrated from API response in fetchDocument/setFromPlanResponse
  // See preferred_tile_ids in PlanDocumentData
};
