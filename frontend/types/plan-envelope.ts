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

  // Suggestions (backend emits, frontend displays only in bootstrap)
  suggested_responses?: string[];
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
