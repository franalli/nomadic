/**
 * Loader action types and configuration.
 * Used to control when and how the progress loader appears.
 */

/**
 * The 5 canonical action types that trigger the progress loader.
 * Each maps to specific UI copy and behavior.
 */
export type LoaderActionType =
  | 'generate_plan' // S0/S1 -> S2, /plan/generate
  | 'update_plan' // Constraint change triggering recomputation
  | 'refresh_deals' // Tile/price refresh only
  | 'create_itinerary' // S2 -> S3, /itinerary/expand
  | 'vertical_fetch'; // Explicit Flights/Stays/Activities search

/**
 * Sub-type for vertical fetch actions.
 */
export type VerticalFetchType = 'flights' | 'stays' | 'activities';

/**
 * Extended loader state with action classification.
 */
export interface ActionLoaderState {
  actionType: LoaderActionType;
  verticalType?: VerticalFetchType; // Only for 'vertical_fetch'
  startTime: number;
  estimatedDurationMs: number;
  stepIndex: number; // Current step in the subtext sequence
  hasTiles?: boolean; // For refresh_deals contextual copy
}

/**
 * Copy configuration for each action type.
 */
export interface LoaderCopyConfig {
  title: string;
  subtexts: string[]; // Sequence of subtext steps
  fallbackSubtext?: string; // Shown after 30s
}

/**
 * Context passed to action classification to help determine action type.
 */
export interface TriggerContext {
  isGeneratePlanTrigger?: boolean;
  isConstraintChange?: boolean;
  isItineraryExpand?: boolean;
}
