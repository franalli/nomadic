/**
 * Types for the centralized PlanDocument.
 * This is the source of truth for branches and tiles.
 *
 * Note: Generated types are available in './generated.ts' via `npm run types:generate`.
 * These manual definitions include stricter non-optional fields that the frontend
 * expects (with defaults applied), while the OpenAPI schema marks them as optional.
 */

import type { Tile } from './tile';

export type UpdatedBy = 'user' | 'planner';

export type BranchTileIds = {
  stays: string[];
  flights: string[];
  activities: string[];
};

export type BranchSelections = {
  stay?: string | null;
  flight?: string | null;
  activities: string[];
};

export type DocumentBranch = {
  id: string;
  label: string;
  description: string;
  destinations: string[];
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  adults?: number | null;
  children?: number | null;
  requires_assistance?: boolean | null;
  budget?: number | null;
  currency?: string | null;
  is_primary: boolean;
  tiles: BranchTileIds;
  selections: BranchSelections;
};

// Booking type toggles - which categories to search for
export type BookingTypes = {
  hotels: boolean;
  flights: boolean;
  ground_transport: boolean;
  activities: boolean;
};

// Flight-specific search settings
export type FlightSettings = {
  round_trip: boolean;
  cabin_class: 'economy' | 'premium_economy' | 'business' | 'first';
  direct_only: boolean;
};

// Hotel-specific search settings
export type HotelSettings = {
  min_stars: number; // 1-5, 0 = no minimum
  amenities: string[]; // e.g., ['wifi', 'pool', 'parking']
};

// Activity-specific search settings
export type ActivitySettings = {
  categories: string[]; // e.g., ['tours', 'experiences', 'outdoor']
  max_duration_hours: number | null; // null = no limit
};

// Ground transport settings - which modes to include
export type TransportSettings = {
  car: boolean;
  train: boolean;
  bus: boolean;
};

export type DocumentTripInputs = {
  destinations: string[];
  origin?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  adults?: number | null;
  children?: number | null;
  requires_assistance?: boolean | null;
  budget?: number | null;
  currency?: string | null;
  missing_fields: string[];
  multi_city_intent?: 'multi_city' | 'separate' | null;
  vibes?: string[];
  booking_types?: BookingTypes;
  flight_settings?: FlightSettings;
  hotel_settings?: HotelSettings;
  activity_settings?: ActivitySettings;
  transport_settings?: TransportSettings;
};

export type DocumentTripInputsPatch = Partial<DocumentTripInputs>;

export type PlanDocumentData = {
  trip_context_id?: number | null;
  trip_inputs: DocumentTripInputs;
  branches: DocumentBranch[];
  tiles: Record<string, Tile>;
  assistant_message?: string | null;
  assistant_message_id?: string | null;
  ready_to_generate?: boolean;
};

export type PlanDocumentResponse = {
  version: number;
  updated_by: UpdatedBy;
  document: PlanDocumentData;
  updated_at: string;
};

export type PlanDocumentPatch = {
  version: number;
  branches?: DocumentBranch[];
  remove_branch_ids?: string[];
  tiles?: Record<string, Tile>;
  remove_tile_ids?: string[];
  selections?: Record<string, BranchSelections>;
  trip_inputs?: DocumentTripInputsPatch;
};
