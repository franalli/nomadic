/**
 * Loader visibility configuration.
 * Defines which operations should show the inline loader based on node type and ETA.
 */

import type {
  LoaderActionType,
  TriggerContext,
  VerticalFetchType,
} from '@/types/loader';

import { SPECIALIST_IDS } from './specialists';

/**
 * ETA thresholds by node type.
 * Operations with ETA below threshold won't show loader.
 *
 * - 0 means "always show" (no threshold)
 * - Higher values mean "only show for slower expected operations"
 */
const LOADER_ETA_THRESHOLDS: Record<string, number> = {
  // Default threshold for unknown nodes
  default: 600,

  // ── v1 graph node names ──
  // Always show for these operations (slow by nature)
  strategy_node: 0,      // 6000-8000ms - strategy planning
  plan_generation: 0,    // Full plan generation
  itinerary_node: 0,     // Itinerary updates

  // Specialist nodes - always show (4000ms+ typically)
  ...Object.fromEntries(SPECIALIST_IDS.map((id) => [`${id}_specialist`, 0])),

  // Multi-step operations - always show
  multi_city_routing: 0,
  deals_search: 0,

  // Quick operations - higher threshold (skip unless unexpectedly slow)
  required_fields_node: 800,
  validation_node: 1000,
  acknowledgment_node: 800,

  // ── v2 tool names (run in parallel with v1 via feature flag) ──
  extract_trip_fields: 800,   // Quick extraction, similar to required_fields_node
  get_specialist_advice: 0,   // Slow — always show (maps to specialist)
  get_local_intel: 0,         // Slow — always show (maps to local_expert)
  search_tiles: 0,            // Slow — always show (maps to logistics)
  validate_plan: 1000,        // Quick validation, similar to validation_node
  build_itinerary: 0,         // Slow — always show (maps to itinerary_node)
};

/**
 * Check if an operation should show the loader based on node type and estimated duration.
 *
 * @param nodeType - The type of node being executed (from SSE node_status event)
 * @param estimatedMs - The estimated duration in milliseconds
 * @returns true if the loader should be shown for this operation
 */
export function shouldShowLoaderForNode(nodeType: string, estimatedMs: number): boolean {
  const threshold = LOADER_ETA_THRESHOLDS[nodeType] ?? LOADER_ETA_THRESHOLDS.default;

  // If threshold is 0, always show (no minimum ETA required)
  if (threshold === 0) {
    return true;
  }

  // Otherwise, only show if estimated duration exceeds threshold
  return estimatedMs >= threshold;
}

/**
 * Node types that map to each action type.
 * Used to classify incoming node_status events.
 */
const ACTION_TYPE_NODE_MAP: Record<string, LoaderActionType> = {
  // ── v1 graph node names ──
  // Generate plan nodes
  strategy_node: 'generate_plan',
  plan_generation: 'generate_plan',
  structure_node: 'generate_plan',

  // Specialist nodes (part of generate_plan)
  ...Object.fromEntries(SPECIALIST_IDS.map((id) => [`${id}_specialist`, 'generate_plan' as const])),

  // Create itinerary nodes
  itinerary_node: 'create_itinerary',

  // Refresh deals nodes
  deals_search: 'refresh_deals',
  price_refresh: 'refresh_deals',

  // Vertical fetch nodes
  flight_search: 'vertical_fetch',
  hotel_search: 'vertical_fetch',
  activity_search: 'vertical_fetch',

  // Multi-city routing (part of generate_plan)
  multi_city_routing: 'generate_plan',

  // ── v2 tool names (run in parallel with v1 via feature flag) ──
  get_specialist_advice: 'generate_plan',
  get_local_intel: 'generate_plan',
  search_tiles: 'generate_plan',
  build_itinerary: 'create_itinerary',
  // Note: extract_trip_fields and validate_plan are quick operations
  // that intentionally don't map to an action type (same as
  // acknowledgment_node / validation_node in v1).
};

/**
 * Map vertical fetch node types to their specific vertical type.
 */
const VERTICAL_FETCH_NODE_MAP: Record<string, VerticalFetchType> = {
  flight_search: 'flights',
  hotel_search: 'stays',
  activity_search: 'activities',
};

/**
 * Result of action classification.
 */
interface ActionClassification {
  actionType: LoaderActionType;
  verticalType?: VerticalFetchType;
}

/**
 * Classify an incoming node_status event into an action type.
 * Returns null if the node should NOT trigger the loader.
 *
 * @param nodeType - The type of node from SSE node_status event
 * @param triggerContext - Optional context about what triggered the operation
 * @returns ActionClassification or null if node should not show loader
 */
export function classifyNodeAction(
  nodeType: string,
  triggerContext?: TriggerContext
): ActionClassification | null {
  // Priority 1: Use trigger context if available (most reliable)
  if (triggerContext?.isGeneratePlanTrigger) {
    return { actionType: 'generate_plan' };
  }
  if (triggerContext?.isItineraryExpand) {
    return { actionType: 'create_itinerary' };
  }

  // Priority 2: Map node type to action type
  const actionType = ACTION_TYPE_NODE_MAP[nodeType];
  if (!actionType) {
    // Node type not recognized - don't show loader
    // This handles pure chat, acknowledgment_node, validation_node, etc.
    return null;
  }

  // For constraint changes when we already have a plan, classify as update_plan
  if (
    triggerContext?.isConstraintChange &&
    actionType === 'generate_plan'
  ) {
    return { actionType: 'update_plan' };
  }

  // Get vertical type if applicable
  const verticalType = VERTICAL_FETCH_NODE_MAP[nodeType];

  return { actionType, verticalType };
}
