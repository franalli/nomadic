/**
 * Loader visibility configuration.
 * Defines which operations should show the inline loader based on node type and ETA.
 */

/**
 * ETA thresholds by node type.
 * Operations with ETA below threshold won't show loader.
 *
 * - 0 means "always show" (no threshold)
 * - Higher values mean "only show for slower expected operations"
 */
export const LOADER_ETA_THRESHOLDS: Record<string, number> = {
  // Default threshold for unknown nodes
  default: 600,

  // Always show for these operations (slow by nature)
  strategy_node: 0,      // 6000-8000ms - strategy planning
  plan_generation: 0,    // Full plan generation
  itinerary_node: 0,     // Itinerary updates

  // Specialist nodes - always show (4000ms+ typically)
  hiking_specialist: 0,
  diving_specialist: 0,
  skiing_specialist: 0,
  cycling_specialist: 0,
  boating_specialist: 0,

  // Multi-step operations - always show
  multi_city_routing: 0,
  deals_search: 0,

  // Quick operations - higher threshold (skip unless unexpectedly slow)
  required_fields_node: 800,
  validation_node: 1000,
  acknowledgment_node: 800,
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
