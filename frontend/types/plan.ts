export type TripInputs = {
  destination?: string | null;
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  traveler_count?: number | null;
  budget?: number | null;
  missing_fields?: string[];
  unchanged_fields?: string[];
};

export type PlanBranch = {
  id: string;
  label: string;
  description: string;
  destination: string;
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  traveler_count?: number | null;
  budget?: number | null;
};
