/**
 * TripInputs is now an alias for DocumentTripInputs.
 * The PlanDocument is the single source of truth for trip state.
 *
 * Note: TripInputs includes an optional `destination` field for backward compatibility
 * with some UI components, but `destinations` (array) is the canonical field.
 */
export type TripInputs = import('./document').DocumentTripInputs & {
  /** @deprecated Use `destinations` array instead */
  destination?: string | null;
};

// Re-export DocumentTripInputs for code that wants the canonical type
export type { DocumentTripInputs } from './document';

// PlanBranch is now an alias for DocumentBranch
// Import DocumentBranch from document.ts for the full type
export type { DocumentBranch as PlanBranch } from './document';
