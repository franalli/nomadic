/**
 * Plan State Envelope Types
 *
 * Single source of truth for frontend state rendering.
 * Backend emits these fields, frontend renders exactly what backend says.
 *
 * IMPORTANT: Frontend must NEVER infer plan_state from other fields.
 */

import type { Tile } from './tile';

// =============================================================================
// Canonical Plan States (Backend-Emitted)
// =============================================================================

/**
 * Backend-authoritative plan state.
 * Frontend renders UI based exclusively on this value.
 */
export type PlanState = 'INCOMPLETE' | 'RESOLVING' | 'STABLE' | 'LOCKED';

/**
 * UI phase - determines suggestion visibility and LQA behavior.
 * - "bootstrap": Chips-only mode, suggestions visible, LQA echo enabled
 * - "expanded": Full planner mode, suggestions hidden
 */
export type UIPhase = 'bootstrap' | 'expanded';

// =============================================================================
// View Mode (Two-Mode System)
// =============================================================================

/**
 * Two-mode system for the main UI.
 * Replaces the old three-mode system (setup/plan/book).
 *
 * - "planning": Unified mode that evolves naturally based on user inputs
 *   - Early: Input gathering + specialist cards (was "setup")
 *   - Late: Day-by-day itinerary + map (was "plan")
 * - "booking": Transaction mode with price comparison and checkout
 *
 * @see docs/ux_unified_architecture.md for full specification
 */
export type ViewMode = 'planning' | 'booking';

/**
 * Planning phase tracking - shows progress within PLANNING mode.
 * Used for the progress indicator UI.
 */
export interface PlanningPhase {
  /** User has specified a destination */
  hasDestination: boolean;
  /** User has specified an origin (for flights) */
  hasOrigin: boolean;
  /** User has specified dates (triggers itinerary generation) */
  hasDates: boolean;
  /** Itinerary has been generated (S3 content exists) */
  hasItinerary: boolean;
  /** User has made minimum selections to proceed to booking */
  isReadyToBook: boolean;
}

/**
 * Compute the current planning phase from document state.
 */
export function computePlanningPhase(
  tripInputs: { destination?: string | null; origin?: string | null; start_date?: string | null } | undefined,
  hasItinerary: boolean,
  hasMinimumSelections: boolean
): PlanningPhase {
  return {
    hasDestination: Boolean(tripInputs?.destination),
    hasOrigin: Boolean(tripInputs?.origin),
    hasDates: Boolean(tripInputs?.start_date),
    hasItinerary,
    isReadyToBook: hasMinimumSelections,
  };
}

/**
 * Compute progress percentage for the planning phase (0-100).
 */
export function computePlanningProgress(phase: PlanningPhase): number {
  const weights = {
    hasDestination: 25,
    hasOrigin: 15,
    hasDates: 30,
    hasItinerary: 20,
    isReadyToBook: 10,
  };

  let progress = 0;
  if (phase.hasDestination) progress += weights.hasDestination;
  if (phase.hasOrigin) progress += weights.hasOrigin;
  if (phase.hasDates) progress += weights.hasDates;
  if (phase.hasItinerary) progress += weights.hasItinerary;
  if (phase.isReadyToBook) progress += weights.isReadyToBook;

  return progress;
}

// =============================================================================
// Resolver (RESOLVING state only)
// =============================================================================

/**
 * Fixed resolver steps - exactly one active at a time.
 */
type ResolverStep =
  | 'processing_constraints'
  | 'matching_inventory'
  | 'updating_itinerary';

/**
 * Resolver progress state.
 * Present ONLY when plan_state = "RESOLVING".
 */
export interface ResolverState {
  active_step: ResolverStep;
  completed_steps: ResolverStep[];
}

// =============================================================================
// Readiness (Constraint Completeness)
// =============================================================================

/**
 * Fixed set of readiness keys for constraint completeness.
 */
type ReadinessKey =
  | 'origin'
  | 'destination'
  | 'start_date'
  | 'end_date'
  | 'travelers'
  | 'budget';

/**
 * Single readiness item for constraint status.
 */
export interface ReadinessItem {
  key: ReadinessKey;
  ok: boolean;
}

// =============================================================================
// Destination Card
// =============================================================================

/**
 * Destination content anchor for the plan.
 */
export interface DestinationCard {
  title: string; // e.g. "Rome"
  subtitle?: string; // e.g. "Your adventure in Rome"
  image_url?: string; // Placeholder OK
}

// =============================================================================
// Booking Status (Per-Tab)
// =============================================================================

/**
 * Booking status states per tab.
 */
type BookingState = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Status for a single booking category.
 */
interface BookingStatusItem {
  state: BookingState;
  summary: string; // Short factual string, no tone, no emoji
}

/**
 * Per-tab booking status.
 */
export interface BookingStatus {
  flights?: BookingStatusItem;
  stays?: BookingStatusItem;
  activities?: BookingStatusItem;
}

// =============================================================================
// Generation State (Progress Tracking)
// =============================================================================

/**
 * Generation state for tracking async operations.
 * Envelope wins if present, else use local UI state.
 */
export interface GenerationState {
  active: boolean;
  stage: 'structure' | 'strategy' | 'itinerary';
  message?: string;
  pct?: number;
}

// =============================================================================
// Planning Phase (Density-Oriented State)
// =============================================================================

/**
 * Planning phases for right-side plan view.
 * Controls what content is shown based on data density, NOT UI mode.
 *
 * Frontend renders based on data availability:
 * - P0: Destination only, no specialists yet
 * - P1: Specialists run, strategy sections present
 * - P2: Tiles fetched, suggestions available
 * - P3: Itinerary validated, ready to book
 */
export type PlanViewState =
  // Core density levels (new)
  | 'P0_MINIMAL'       // Destination only, no specialists yet
  | 'P1_ENRICHED'      // Specialists run, strategy sections present
  | 'P2_LOGISTICS'     // Tiles fetched, suggestions available
  | 'P3_FINALIZED'     // Itinerary validated, ready to book
  | 'P3_EDITING'       // User editing itinerary assumptions/constraints
  | 'P3_BLOCKED'       // Itinerary requested but blocked (missing locks)
  // Legacy aliases (for migration - will be removed)
  // Intentional: FE-only sentinel — not present in backend PlanEnvelope schema
  | 'S0_EMPTY'         // FE-only reset sentinel, never emitted by backend -> P0_MINIMAL
  | 'S0_BOOTSTRAP'     // -> P0_MINIMAL
  | 'S1_FRAMING'       // -> P0_MINIMAL (merged)
  | 'S2_STRATEGY_READY' // -> P1_ENRICHED
  | 'S2_BLOCKED'       // -> P1_ENRICHED (handled by data checks)
  | 'S3_ITINERARY_READY' // -> P3_FINALIZED
  | 'S3_EDITING'       // -> P3_EDITING
  | 'S3_BLOCKED'       // -> P3_BLOCKED
  | 'S3_PARTIAL_CONFLICT'; // Partial timeline with unschedulable blocks

/**
 * Normalize legacy S* values to new P* values.
 * Use this helper to handle both old and new backend responses.
 */
export function normalizePlanViewState(state: PlanViewState): PlanViewState {
  switch (state) {
    case 'S0_EMPTY':
    case 'S0_BOOTSTRAP':
    case 'S1_FRAMING':
      return 'P0_MINIMAL';
    case 'S2_STRATEGY_READY':
    case 'S2_BLOCKED':
      return 'P1_ENRICHED';
    case 'S3_ITINERARY_READY':
      return 'P3_FINALIZED';
    case 'S3_EDITING':
      return 'P3_EDITING';
    case 'S3_BLOCKED':
      return 'P3_BLOCKED';
    case 'S3_PARTIAL_CONFLICT':
      return 'P3_BLOCKED'; // Partial timeline shown with conflict banner
    default:
      return state; // Already a P* value
  }
}

/**
 * Booking artifacts - counts of tiles produced by this agent.
 */
interface BookingArtifacts {
  activities_count: number;
  hotels_count: number;
}

// =============================================================================
// Travel Intelligence Types (12-Category Local Expert)
// =============================================================================

export interface TippingInfo {
  restaurants?: string;
  taxis?: string;
  hotels?: string;
}

export interface TypicalCosts {
  budget_meal?: string;
  mid_range_meal?: string;
  beer?: string;
  taxi_per_km?: string;
  attraction_entry?: string;
}

export interface DailyBudget {
  backpacker?: string;
  mid_range?: string;
  luxury?: string;
}

export interface MoneyCosts {
  currency?: string;
  exchange_tip?: string;
  atm_note?: string;
  tipping?: TippingInfo;
  typical_costs?: TypicalCosts;
  daily_budget?: DailyBudget;
  haggling?: string;
}

export interface AirportTransfer {
  method: string;
  price?: string;
  time?: string;
  tip?: string;
}

export interface PublicTransit {
  has_metro?: boolean;
  has_bus?: boolean;
  transit_card?: string;
  cost_per_ride?: string;
}

export interface ScooterRental {
  available?: boolean;
  daily_rate?: string;
  license_required?: boolean;
  recommendation?: string;
}

export interface Transportation {
  airport_to_city?: AirportTransfer[];
  public_transit?: PublicTransit;
  ride_apps?: string[];
  scooter_rental?: ScooterRental;
  traffic_note?: string;
}

export interface DressCode {
  temples?: string;
  beaches?: string;
  restaurants?: string;
}

export interface CulturalNorms {
  dress_code?: DressCode;
  religious_notes?: string;
  greetings?: string;
  photo_etiquette?: string;
  dining_etiquette?: string[];
  lgbtq_friendly?: string;
  important_taboos?: string[];
}

export interface SafetyHealth {
  overall_safety?: string;
  tap_water_safe?: boolean;
  street_food_safe?: boolean;
  common_concerns?: string[];
  emergency_number?: string;
  nearest_hospital?: string;
  vaccinations?: string[];
  areas_to_avoid?: string[];
}

export interface VisaEntry {
  visa_free_for?: string[];
  visa_on_arrival?: boolean;
  max_stay_days?: number;
  passport_validity_months?: number;
  key_requirements?: string[];
  immigration_tip?: string;
}

export interface Connectivity {
  best_sim_provider?: string;
  sim_cost?: string;
  where_to_buy?: string;
  esim_works?: boolean;
  wifi_quality?: string;
  essential_apps?: string[];
  vpn_needed?: boolean;
}

export interface Festival {
  name: string;
  when?: string;
  impact?: string;
}

export interface Seasonality {
  best_months?: string[];
  avoid_months?: string[];
  high_season?: string;
  rainy_season?: string;
  major_festivals?: Festival[];
  current_season_tip?: string;
}

export interface MustDoExperience {
  name: string;
  why?: string;
  booking?: string;
  best_time?: string;
  cost?: string;
}

export interface DayTrip {
  destination: string;
  distance?: string;
  highlight?: string;
}

export interface HiddenGem {
  name: string;
  why?: string;
  tip?: string;
}

export interface ThingsToDo {
  must_do?: MustDoExperience[];
  day_trips?: DayTrip[];
  hidden_gems?: HiddenGem[];
  skip_these?: string[];
}

export interface NeighborhoodInfo {
  name: string;
  vibe?: string;
  best_for?: string[];
  price_range?: string;
  walkability?: string;
}

export interface Neighborhoods {
  where_to_stay?: NeighborhoodInfo[];
  avoid_staying_in?: string[];
}

export interface AccommodationPrices {
  hostel?: string;
  budget_hotel?: string;
  mid_range?: string;
  luxury?: string;
}

export interface AccommodationInfo {
  types_available?: string[];
  booking_platforms?: string[];
  price_ranges?: AccommodationPrices;
  book_ahead?: string;
}

export interface ScamInfo {
  name: string;
  how_it_works?: string;
  how_to_avoid?: string;
}

export interface ScamsTraps {
  common_scams?: ScamInfo[];
  tourist_traps?: string[];
  taxi_scam_tip?: string;
  general_advice?: string;
}

export interface ElectricalInfo {
  plug_type?: string;
  voltage?: string;
  adapter_needed?: boolean;
}

export interface PackingInfo {
  must_pack?: string[];
  dont_bring?: string[];
  buy_locally?: string[];
  electrical?: ElectricalInfo;
  clothing_tips?: string[];
}

export interface DestinationOverview {
  tagline?: string;
  best_for?: string[];
  vibe?: string;
}

/**
 * Comprehensive travel intelligence from Local Expert.
 * Contains all 12 categories of destination knowledge.
 */
export interface TravelIntelligence {
  destination_overview?: DestinationOverview;
  visa_entry?: VisaEntry;
  safety_health?: SafetyHealth;
  money_costs?: MoneyCosts;
  transportation?: Transportation;
  cultural_norms?: CulturalNorms;
  connectivity?: Connectivity;
  seasonality?: Seasonality;
  things_to_do?: ThingsToDo;
  neighborhoods?: Neighborhoods;
  accommodation?: AccommodationInfo;
  scams_traps?: ScamsTraps;
  packing?: PackingInfo;
  quick_tips?: string[];
}

// =============================================================================
// Strategy Section
// =============================================================================

/**
 * A strategy section for Stage 2 view - one card per executed strategy topic.
 *
 * NOTE: Agent status is COMPUTED by the UI from pending_strategy_topics + executed_strategy_topics.
 * Do NOT add a status field here - compute it using computeAgentStatus() helper.
 */
export interface StrategySection {
  id: string;
  title: string;
  subtitle?: string; // e.g., "Dubai Trip"
  specialist_type?: string; // e.g., "hiking", "diving", "general"

  // Feasibility state (from Constraint Engine)
  feasibility_status?: 'feasible' | 'caveat' | 'infeasible';
  feasibility_reason?: string; // e.g., "Indoor skiing only (SnowWorld)"
  alternative_suggestion?: string; // e.g., "Consider Chamonix, Zermatt, or Niseko"

  // Collapsed state
  one_liner?: string; // max 60 chars
  editorial_one_liner?: string; // Evocative one-liner for General specialist (Magazine style)
  principles: string[]; // max 4 items, 50 chars each

  // Expanded state
  must_dos: string[]; // max 5 items, 110 chars each
  optional_upgrades: string[]; // max 3 items
  logistics_notes: string[]; // max 4 items
  tradeoffs_summary?: string; // max 300 chars

  // Booking artifacts - shortlist counts from this agent
  booking_artifacts?: BookingArtifacts;

  // Impact areas - which parts of the plan this agent affects
  impact_areas?: string[]; // e.g., ["Schedule", "Location", "Gear"]

  // Technical log data for "System Log" display
  constraints_applied?: Array<{
    rule: string;
    type: string;
    reason?: string;
  }>;

  // Typed content blocks — mirrors content_added as a first-class field
  content_blocks?: Array<Record<string, unknown>>;

  content_added?: Array<{
    title: string;
    day?: number;
    type?: string;
    description?: string;  // Rich description of the content
    logic_hook?: string;   // "Why this matters" tip (e.g., "Indoor - Summer safe")
    image_url?: string;    // Curated thumbnail image for demo destinations
    coordinates?: [number, number];  // [lng, lat] for Mapbox - Bridge Mode map POIs
  }>;

  // For General Agent: trip parameters summary (inventory counts from tiles, not here)
  trip_summary?: {
    destination: string;
    dates: string;
    travelers: string;
  };

  // Destination gallery - "Vibe Trio" images for Local Expert card (hero destinations only)
  // Structure matches backend placeholders.py get_destination_gallery()
  destination_gallery?: Array<{
    label: string;     // e.g., "Destination", "Culture", "Adventure"
    image_url: string; // Unsplash URL
  }>;

  // Vibe Trio - Magazine style images for General specialist (generated from Unsplash)
  // @see docs/ux_unified_architecture.md Section XII - Magazine Style
  vibe_trio?: Array<{
    label: string;    // e.g., "City Highlights"
    image_url: string; // Unsplash URL
  }>;

  // Hero Image - Single focused action shot for Niche Specialists (Diving, Hiking, etc.)
  // @see docs/ux_unified_architecture.md Section XII - Activity Layout
  hero_image?: string;

  // NEW: Comprehensive 12-category travel intelligence (Local Expert only)
  // Contains visa, safety, money, transport, culture, connectivity, seasonality,
  // things to do, neighborhoods, accommodation, scams, and packing info
  travel_intelligence?: TravelIntelligence;
  local_expert_enrichment?: {
    state?: 'ready' | 'pending' | 'failed' | string;
    error_code?: string | null;
    updated_at?: string;
  };

  // Provenance (debug only, not shown in UI)
  strategy_node_id?: string;
  strategy_version?: string;

  // Legacy field for backward compatibility
  bullets: string[];
}

/**
 * Agent status type - computed by UI, not stored on StrategySection.
 */
export type AgentStatus = 'ready' | 'updating' | 'needs_input';

/**
 * Compute agent status from pending and executed topics.
 * Use this instead of storing status on StrategySection.
 */
export function computeAgentStatus(
  topic: string,
  pendingTopics: string[],
  executedTopics: string[]
): AgentStatus {
  if (pendingTopics.includes(topic)) return 'updating';
  if (executedTopics.includes(topic)) return 'ready';
  return 'needs_input';
}

/**
 * An open decision that needs user input (shown in Stage 2).
 */
export interface OpenDecision {
  id: string;
  statement: string; // Statement form, not question (e.g., "Trip duration not confirmed")
  related_field?: string; // Which trip input field this relates to
  is_blocking: boolean; // If true, blocks Stage 3
}

/**
 * A single activity block within a day (Stage 3).
 *
 * Client-side only fields (not sent by backend):
 * - `is_skeleton` -- ghost timeline placeholder for unplanned days
 * - `specialist_type` -- specialist type for ghost blocks (e.g., "diving", "hiking")
 * - `unschedulable` / `unschedulable_reason` / `unschedulable_days_needed` -- partial timeline markers
 */
export interface DayBlock {
  id?: string; // Unique block identifier for scroll spy
  period: 'morning' | 'afternoon' | 'evening';
  activity_type: string; // e.g., "moderate hike", "city stroll"
  intensity?: 'light' | 'moderate' | 'challenging';
  summary: string; // ≤15 words, no times/prices
  // Buffer/Safety block fields (for No-Fly intervals, acclimatization, etc.)
  is_buffer?: boolean;
  buffer_type?: 'no_fly' | 'rest_day' | 'acclimatization' | 'arrival' | 'departure';
  buffer_reason?: string; // e.g., "PADI Standard - 24h surface interval before flying"
  // Specialist constraints (e.g., "24h No-Fly Buffer", "Altitude limit")
  constraints?: string[];
  // Price estimate for Plan mode display (~$150)
  price_estimate?: number;
  // Coordinates for map integration
  coordinates?: { lat: number; lng: number };
  // Ghost timeline: skeleton placeholder for unplanned days
  is_skeleton?: boolean;
  // Specialist type for ghost blocks (e.g., "diving", "hiking")
  specialist_type?: string;
  // Explicit activity model axes (domain + provenance)
  activity_domain?: 'tier1' | 'tier2';
  activity_provenance?: 'ai_suggested' | 'user_browse_added';
  // Canonical map pin category (e.g., "food", "cycling")
  map_type?: string;

  // === NEW: Rich content fields (S3 Itinerary View) ===
  image_url?: string; // Activity thumbnail from specialist
  duration?: string; // "4 hours", "Half day"
  rating?: number; // Google Places star rating (browse-added activities)
  review_count?: number; // Google Places review count
  price_level?: number;  // Google Places price level (0=free, 1=$, 2=$$, 3=$$$, 4=$$$$)
  google_place_id?: string; // Google Places ID
  deeplink?: string;        // Google Maps URL

  // === NEW: Logistics layer (hard times) ===
  scheduled_time?: string; // "08:00 AM" for flights/check-in
  logistics_details?: string; // Terminal info, hotel address
  hotel_name?: string; // For check-in/out blocks

  // === NEW: Booking integration ===
  booked_tile?: Tile; // Embedded confirmed booking
  requires_booking?: boolean; // True = show ghost slot in UI
  booking_category?: 'hotel' | 'flight' | 'activity';

  // === NEW: Preference attribution (shows why tile was selected) ===
  preference_status?: 'user_preferred' | 'ai_selected' | 'ai_override';
  preference_override_reason?: string; // Why AI overrode user preference
  alternative_tile_id?: string; // ID of user's preferred tile if AI overrode

  // === NEW: Inline constraint badges (shows applied constraints) ===
  active_constraints?: Array<{
    id: string;
    severity: 'warning' | 'info' | 'success' | 'blocking';
    icon: string;
    title: string;
    description: string;
  }>;

  // === NEW: Unschedulable marker (for partial timeline) ===
  unschedulable?: boolean;
  unschedulable_reason?: string;
  unschedulable_days_needed?: number;
}

/**
 * A single day in the itinerary (Stage 3).
 */
export interface DayCard {
  day_number: number;
  date?: string; // ISO date string, e.g. "2025-02-12"
  label: string; // e.g., "Arrival + light activity", "Main hike day"
  /** Client-side only -- computed from blocks, not sent by backend */
  subtitle?: string;
  blocks: DayBlock[]; // Max 3 blocks
}

/**
 * Overview stats for Stage 3 itinerary.
 */
export interface ItineraryOverview {
  duration_label: string; // e.g., "3 days"
  base_structure: string; // e.g., "Single base + day excursions"
  activity_density: string; // e.g., "1 major activity/day"
}

/**
 * Assumptions and flexible elements for Stage 3.
 */
export interface ItineraryAssumptions {
  assumptions: string[]; // Max 4 items
  flexible_elements: string[]; // Max 3 items
}

/**
 * View model for stage-aware rendering.
 * Populated based on current PlanViewState.
 */
export interface PlanViewModel {
  // Stage 2 content
  strategy_sections?: StrategySection[];
  executed_strategy_topics?: string[]; // Topics that ran: ["hiking", "diving"]
  pending_strategy_topics?: string[]; // Topics being generated (optimistic UI)
  open_decisions?: OpenDecision[];

  // Stage 3 content
  itinerary_overview?: ItineraryOverview;
  day_cards?: DayCard[];
  itinerary_assumptions?: ItineraryAssumptions;

  // Flags
  needs_refresh?: boolean;
  can_expand_to_itinerary?: boolean;
}

// =============================================================================
// Receipt System
// =============================================================================

/**
 * Keys for applied updates - matches backend CanonicalUIKey.
 */
export type AppliedUpdateKey =
  | 'origin'
  | 'destination'
  | 'dates'
  | 'travelers'
  | 'budget';

/**
 * Conflict codes - locked enum, frontend renders deterministic copy.
 */
export type ConflictCode =
  | 'date_range_invalid'
  | 'date_past'
  | 'budget_exceeded'
  | 'traveler_mismatch'
  | 'destination_unreachable'
  | 'duration_mismatch';

/**
 * Structured conflict for UI rendering (no freeform text).
 */
export interface Conflict {
  scope: AppliedUpdateKey;
  related_constraints: AppliedUpdateKey[];
  code: ConflictCode;
}

/**
 * Undo snapshot for rollback capability.
 */
export interface UndoSnapshot {
  v: number;
  trip_inputs: Record<string, unknown>;
}

/**
 * Ack status for collapsible messages.
 * - 'pending': FE-only optimistic state (set before backend ack arrives, never from backend)
 * - All others: from backend AckUpdate response
 */
export type AckStatus = 'pending' | 'applied' | 'partial' | 'no_change' | 'needs_clarification' | 'failed' | 'rejected';

/**
 * Detailed update info for collapsible message UI.
 */
export interface AckUpdate {
  field: string;  // Canonical UI key
  to: string;     // New value (human-readable)
  from_value?: string;  // Previous value if overwritten
}

/**
 * Update provenance for debugging.
 */
export type UpdateProvenance = 'lqa' | 'extractor' | 'user_edit';
