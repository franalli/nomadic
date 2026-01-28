/**
 * Plan State Envelope Types
 *
 * Single source of truth for frontend state rendering.
 * Backend emits these fields, frontend renders exactly what backend says.
 *
 * IMPORTANT: Frontend must NEVER infer plan_state from other fields.
 */

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
// Resolver (RESOLVING state only)
// =============================================================================

/**
 * Fixed resolver steps - exactly one active at a time.
 */
export type ResolverStep =
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

/**
 * Fixed order of resolver steps for rendering.
 */
export const RESOLVER_STEPS: ResolverStep[] = [
  'processing_constraints',
  'matching_inventory',
  'updating_itinerary',
];

// =============================================================================
// Readiness (Constraint Completeness)
// =============================================================================

/**
 * Fixed set of readiness keys for constraint completeness.
 */
export type ReadinessKey =
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

/**
 * Trip Health status for General Agent dashboard.
 * Shows constraint validation, inventory counts, and alerts.
 */
export interface TripHealth {
  /** Constraint validation status (green/yellow/red) */
  constraints: Array<{
    key: ReadinessKey;
    status: 'valid' | 'warning' | 'error';
    label: string;
  }>;
  /** Inventory counts from tiles */
  inventory: {
    hotels: number;
    flights: number;
    activities: number;
  };
  /** Critical alerts from open_decisions where is_blocking: true */
  alerts: Array<{
    level: 'warning' | 'error';
    message: string;
  }>;
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
export type BookingState = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Status for a single booking category.
 */
export interface BookingStatusItem {
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
// Plan View State Machine (Stage-Aware Right-Side View)
// =============================================================================

/**
 * State machine states for right-side plan view.
 * Controls what content is shown in the plan panel.
 */
export type PlanViewState =
  | 'S0_BOOTSTRAP' // No plan yet (or reset). Placeholders only.
  | 'S1_FRAMING' // Stage 1 output available (shortlist/skeleton)
  | 'S2_STRATEGY_READY' // All relevant Stage 2 strategy nodes complete
  | 'S2_BLOCKED' // Stage 2 incomplete due to missing critical fields
  | 'S3_ITINERARY_READY' // Itinerary generated (day cards)
  | 'S3_EDITING' // User editing itinerary assumptions/constraints
  | 'S3_BLOCKED'; // Stage 3 requested but blocked (missing locks)

/**
 * Plan view events for state machine transitions.
 */
export type PlanViewEvent =
  | { type: 'E_USER_INPUT'; payload?: unknown }
  | { type: 'E_CLICK_GENERATE_PLAN' }
  | { type: 'E_STAGE1_DONE'; payload: unknown }
  | { type: 'E_STAGE2_DONE'; payloads: Record<string, unknown> }
  | { type: 'E_CLICK_EXPAND_TO_ITINERARY' }
  | { type: 'E_STAGE3_DONE'; payload: unknown }
  | { type: 'E_CLICK_VIEW_BOOKING_OPTIONS' }
  | { type: 'E_RESET' };

/**
 * Booking artifacts - counts of tiles produced by this agent.
 */
export interface BookingArtifacts {
  activities_count: number;
  hotels_count: number;
}

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

  content_added?: Array<{
    title: string;
    day?: number;
    type?: string;
    description?: string;  // Rich description of the content
    logic_hook?: string;   // "Why this matters" tip (e.g., "Indoor - Summer safe")
    image_url?: string;    // Curated thumbnail image for demo destinations
  }>;

  // For General Agent: trip parameters summary (inventory counts from tiles, not here)
  trip_summary?: {
    destination: string;
    dates: string;
    travelers: string;
  };

  // Destination gallery - "Vibe Trio" images for Local Expert card (hero destinations only)
  destination_gallery?: Array<{
    url: string;
    alt: string;
  }>;

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
}

/**
 * A single day in the itinerary (Stage 3).
 */
export interface DayCard {
  day_number: number;
  label: string; // e.g., "Arrival + light activity", "Main hike day"
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
 */
export type AckStatus = 'applied' | 'partial' | 'no_change' | 'needs_clarification' | 'failed';

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

// =============================================================================
// Plan Envelope (Full Response Shape)
// =============================================================================

/**
 * Complete plan state envelope from backend.
 * This is the source of truth for UI rendering.
 */
export interface PlanEnvelope {
  // Backend-authoritative state
  ui_phase: UIPhase;
  plan_state: PlanState;

  // RESOLVING only
  resolver: ResolverState | null;

  // Constraint completeness (recommended always)
  readiness: ReadinessItem[];

  // Content anchor
  destination_card?: DestinationCard;

  // Tabs + micro-status
  booking_status?: BookingStatus;

  // Receipt system
  applied_updates?: AppliedUpdateKey[];
  conflicts?: Conflict[];
  undo_snapshot?: UndoSnapshot | null;
  update_provenance?: UpdateProvenance | null;
  // Detailed ack payload for collapsible messages
  ack_status?: AckStatus;
  ack_updates?: AckUpdate[];

  // Suggestions (backend emits, frontend displays only in bootstrap)
  suggested_responses?: string[];

  // ==========================================================================
  // Generation State (Progress Tracking)
  // ==========================================================================
  /** Generation progress - envelope wins if present, else use local UI state */
  generation?: GenerationState;

  // ==========================================================================
  // Plan View State Machine (Stage-Aware Right-Side View)
  // ==========================================================================
  plan_view_state?: PlanViewState;

  // Stage 2 content (populated when plan_view_state in S2_*)
  strategy_sections?: StrategySection[];
  executed_strategy_topics?: string[]; // Topics that ran: ["hiking", "diving"]
  open_decisions?: OpenDecision[];

  // Stage 3 content (populated when plan_view_state in S3_*)
  itinerary_overview?: ItineraryOverview;
  day_cards?: DayCard[];
  itinerary_assumptions?: ItineraryAssumptions;

  // State flags
  needs_refresh?: boolean;
  can_expand_to_itinerary?: boolean;
}

// =============================================================================
// Helper Functions
// =============================================================================

/**
 * Check if suggestions should be shown based on plan state.
 * Shows suggestions when plan is incomplete (missing constraints).
 */
export function shouldShowSuggestions(planState: PlanState): boolean {
  return planState === 'INCOMPLETE';
}

/**
 * Get human-readable label for a readiness key.
 */
export function getReadinessLabel(key: ReadinessKey): string {
  const labels: Record<ReadinessKey, string> = {
    origin: 'Origin',
    destination: 'Destination',
    start_date: 'Start date',
    end_date: 'End date',
    travelers: 'Travelers',
    budget: 'Budget',
  };
  return labels[key];
}

/**
 * Get human-readable label for a resolver step.
 */
export function getResolverStepLabel(step: ResolverStep): string {
  const labels: Record<ResolverStep, string> = {
    processing_constraints: 'Processing constraints',
    matching_inventory: 'Matching inventory',
    updating_itinerary: 'Updating itinerary',
  };
  return labels[step];
}
