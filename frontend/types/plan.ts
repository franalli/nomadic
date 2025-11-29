export type TripInputs = {
  destination?: string | null;
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  traveler_count?: number | null;
  budget?: number | null;
  missing_fields?: string[];
};

// PlanBranch is now an alias for DocumentBranch
// Import DocumentBranch from document.ts for the full type
export type { DocumentBranch as PlanBranch } from './document';
