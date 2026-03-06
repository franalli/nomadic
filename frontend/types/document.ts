/**
 * Types for the centralized PlanDocument.
 * This is the source of truth for branches and tiles.
 *
 * Note: Generated types are available in './generated.ts' via `npm run types:generate`.
 * These manual definitions include stricter non-optional fields that the frontend
 * expects (with defaults applied), while the OpenAPI schema marks them as optional.
 */

import type {
  AckStatus,
  AckUpdate,
  AppliedUpdateKey,
  BookingStatus,
  Conflict,
  DayCard,
  DestinationCard,
  ItineraryAssumptions,
  ItineraryOverview,
  OpenDecision,
  PlanState,
  PlanViewState,
  ReadinessItem,
  ResolverState,
  StrategySection,
  UIPhase,
  UndoSnapshot,
  UpdateProvenance,
} from './plan-envelope';
import type { Tile } from './tile';

export type UpdatedBy = 'user' | 'planner';

type BranchTileIds = {
  stays: string[];
  flights: string[];
  activities: string[];
};

export type BranchSelections = {
  stay?: string | null;
  flight?: string | null;
  activities: string[];
};

export type DocumentBranch = {
  id: string;
  label: string;
  description: string;
  destination?: string | null;
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  adults?: number | null;
  children?: number | null;
  requires_assistance?: boolean | null;
  budget?: number | null;
  currency?: string | null;
  is_primary: boolean;
  tiles: BranchTileIds;
  selections: BranchSelections;
  // Dynamic images from backend (Unsplash)
  image_url?: string | null;
  hero_images?: string[];
  // Strategy-enriched fields (populated by strategy nodes)
  vibe?: string | null;
  focus?: string | null;
  highlights?: string[];
  flow?: string[];
  notes?: string[];
};

// Plan regeneration status for reactive updates
export type PlanStatus = 'ready' | 'stale' | 'updating';

// Tri-state booking type: off (user disabled), suggested (default/auto), on (user enabled)
export type BookingTypeState = 'off' | 'suggested' | 'on';

/**
 * Check if a booking type state is enabled (suggested or on).
 * Handles legacy boolean values during migration.
 */
export function isBookingEnabled(
  state: BookingTypeState | boolean | undefined | null
): boolean {
  if (state === null || state === undefined) {
    return false;
  }
  // Handle legacy boolean values
  if (typeof state === 'boolean') {
    return state;
  }
  return state === 'suggested' || state === 'on';
}

// Booking type toggles - which categories to search for
// Uses tri-state model:
// - 'off': User explicitly disabled, never show or search
// - 'suggested': Default state, show provisional items
// - 'on': User explicitly enabled, may require confirmation gates
export type BookingTypes = {
  hotels: BookingTypeState;
  flights: BookingTypeState;
  ground_transport: BookingTypeState;
  activities: BookingTypeState;
};

// Flight-specific search settings
export type FlightSettings = {
  round_trip: boolean;
  cabin_class: 'economy' | 'premium_economy' | 'business' | 'first';
  direct_only: boolean;
};

// Hotel-specific search settings
export type HotelSettings = {
  min_stars: number; // 1-5, 0 = no minimum
  amenities: string[]; // e.g., ['wifi', 'pool', 'parking']
  style?: string; // e.g., 'boutique', 'resort', 'hostel'
  location?: string; // e.g., 'beachfront', 'city center', 'near airport'
};

// Activity-specific search settings
export type ActivitySettings = {
  categories: string[]; // e.g., ['tours', 'experiences', 'outdoor']
  skill_level: string | null; // "beginner", "intermediate", "advanced"
  day_preferences?: Record<string, number>; // {"diving": 3, "hiking": 2}
  activities_per_day?: number | null; // 1-3 from UI, null = auto
};

// Ground transport settings - which modes to include
export type TransportSettings = {
  car: boolean;
  train: boolean;
  bus: boolean;
};

export type DocumentTripInputs = {
  destination?: string | null;
  destination_iata?: string | null;
  origin?: string | null;
  origin_iata?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  adults?: number | null;
  children?: number | null;
  requires_assistance?: boolean | null;
  budget?: number | null;
  currency?: string | null;
  missing_fields: string[];
  booking_types?: BookingTypes;
  flight_settings?: FlightSettings;
  hotel_settings?: HotelSettings;
  activity_settings?: ActivitySettings;
  transport_settings?: TransportSettings;
  // Flexible dates support - for CTA gating
  date_flex?: boolean;
  trip_duration?: number | null;
  date_window_start?: string | null;
  date_window_end?: string | null;
  country_code?: string | null;
};

export type DocumentTripInputsPatch = Partial<DocumentTripInputs>;

export type SuggestionChipMeta = {
  chip_type: 'cta' | 'follow_up' | 'setting';
  category: string;
  icon?: string | null;
};

/** Structured suggestion chip from backend (Stage 11B) */
export interface SuggestionChip {
  message: string;
  action_type: 'send_message' | 'open_pill' | 'trigger_action';
  action_target?: string | null;
  chip_type: 'cta' | 'follow_up' | 'setting';
  category: string;
  icon?: string | null;
}

export type PlanDocumentData = {
  trip_context_id?: number | null;
  trip_inputs: DocumentTripInputs;
  branches: DocumentBranch[];
  tiles: Record<string, Tile>;
  assistant_message?: string | null;
  assistant_message_id?: string | null;
  ready_to_generate?: boolean;
  suggested_responses?: string[];
  suggested_response_meta?: SuggestionChipMeta[];
  suggestion_chips?: SuggestionChip[];

  // Change tracking for UI receipts (existing)
  applied_updates?: AppliedUpdateKey[];
  conflicts?: Conflict[];
  undo_snapshot?: UndoSnapshot | null;
  update_provenance?: UpdateProvenance | null;
  // Detailed ack payload for collapsible messages
  ack_status?: AckStatus;
  ack_updates?: AckUpdate[];

  // ==========================================================================
  // Plan State Envelope - unified frontend state (populated at response time)
  // ==========================================================================
  /** Backend-authoritative state - frontend must NOT infer from other fields */
  plan_state?: PlanState;
  /** UI phase - chips-only bootstrap vs full planner */
  ui_phase?: UIPhase;
  /** Resolver progress (present ONLY when plan_state = "RESOLVING") */
  resolver?: ResolverState | null;
  /** Constraint completeness for diagnostic panel */
  readiness?: ReadinessItem[];
  /** Destination content anchor */
  destination_card?: DestinationCard | null;
  /** Per-tab booking status (factual, no tone, no emoji) */
  booking_status?: BookingStatus | null;

  // ==========================================================================
  // Plan View State Machine (Stage-Aware Right-Side View)
  // ==========================================================================
  /** State machine state - determines what content to show in right panel */
  plan_view_state?: PlanViewState;

  /** Stage 2 content (populated when plan_view_state in S2_*) */
  strategy_sections?: StrategySection[];
  executed_strategy_topics?: string[]; // Topics that ran: ["hiking", "diving"]
  pending_strategy_topics?: string[]; // Topics being generated (optimistic UI)
  open_decisions?: OpenDecision[];

  /** Stage 3 content (populated when plan_view_state in S3_*) */
  itinerary_overview?: ItineraryOverview | null;
  day_cards?: DayCard[];
  itinerary_assumptions?: ItineraryAssumptions | null;

  /** State flags */
  needs_refresh?: boolean;
  can_expand_to_itinerary?: boolean;

  // ==========================================================================
  // User Preferences (synced to DB, hydrated on refresh)
  // ==========================================================================
  /** Heart-selected tiles - used for AI weighting in itinerary generation */
  preferred_tile_ids?: string[];

  /** User-pinned tiles persisted by backend for fill-day survival across rebuilds */
  user_pinned_tiles?: Record<string, unknown>;

  /** Origin update flag - frontend should trigger flight fetch when true */
  origin_just_set?: boolean;

  /** When true, tiles should REPLACE existing (not merge additively) */
  tiles_replaced?: boolean;

  // ==========================================================================
  // Constraint Validation (Trip DNA bar badges)
  // ==========================================================================
  /** Constraints that passed validation (green badges) */
  constraints_validated?: Array<{
    constraint_id: string;
    rule: string;
    status: 'satisfied';
    specialist: string;
    label: string;
  }>;
  /** Constraints that were violated (amber badges) */
  constraint_violations?: Array<{
    code: string;
    message: string;
    severity: string;
    category: string;
    rule?: string;
    suggested_action?: string;
  }>;

  /** Tier-1-suppressed activity tiles stashed by logistics_node (for Browse Activities sheet) */
  browseable_activities?: Array<Record<string, unknown>>;
};

export type PlanDocumentResponse = {
  version: number;
  updated_by: UpdatedBy;
  document: PlanDocumentData;
  updated_at: string;
  changes_made?: boolean;
};

export type PlanDocumentPatch = {
  version: number;
  branches?: DocumentBranch[];
  remove_branch_ids?: string[];
  tiles?: Record<string, Tile>;
  remove_tile_ids?: string[];
  selections?: Record<string, BranchSelections>;
  trip_inputs?: DocumentTripInputsPatch;
  preferred_tile_ids?: string[];
};

// Graph planner types (superset of PlanDocumentResponse)
type GraphPlanTokens = {
  prompt: number;
  completion: number;
  total: number;
};

type EntityConfidenceInfo = {
  value: string;
  confidence: number;
  needs_confirmation: boolean;
  fuzzy_suggestion?: string | null;
  ambiguity_type?: string | null;
};

type ExtractionConfidenceInfo = {
  overall: number;
  level: string;
  destinations?: EntityConfidenceInfo[];
  origin?: EntityConfidenceInfo | null;
  detected_language?: string | null;
  is_english?: boolean;
  typo_suggestions?: string[];
};

type GraphPlanObservability = {
  tokens: GraphPlanTokens;
  model_used?: string | null;
  router_intent?: string | null;
  strategy_topic?: string | null;
  today_iso?: string | null;
  ready_to_generate_prev?: boolean;
  ready_to_generate_now?: boolean;
  extraction_confidence?: ExtractionConfidenceInfo | null;
  short_circuit_type?: string | null;
  llm_calls_made?: number;
  cache_hits?: number;
  confidence_routing?: string | null;
};

export type GraphPlanResponse = PlanDocumentResponse & {
  session_state: Record<string, unknown>;
  request_id: string;
  observability?: GraphPlanObservability | null;
  changes_made: boolean;
};
