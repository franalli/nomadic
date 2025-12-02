/**
 * TripInputs is now an alias for DocumentTripInputs.
 * The PlanDocument is the single source of truth for trip state.
 */
export type TripInputs = import('./document').DocumentTripInputs;

// PlanBranch is now an alias for DocumentBranch
// Import DocumentBranch from document.ts for the full type
export type { DocumentBranch as PlanBranch } from './document';
