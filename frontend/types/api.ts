import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

// frontend/types/api.ts
export interface PlanRequest {
  user_id?: string;
  session_id?: string;
  message: string;
  origin?: string;
  start_date?: string;
  end_date?: string;
  budget_bucket?: string;
  group_size?: number;
  vibes: string[];
}

export interface PlanResponse {
  branches: PlanBranch[];
  tiles: Tile[];
  trip_context_id?: number | null;
  primary_branch_id?: string | null;
  tiles_request_id?: string | null;
  tiles_summary?: Record<string, unknown> | null;
}

export interface TilesSearchRequest {
  user_id?: string;
  branch_id?: number;
  session_id?: string;
  trip_context_id?: number;
  origin?: string;
  destination?: string;
  destination_hint?: string;
  start_date?: string;
  end_date?: string;
  budget_bucket?: string;
  group_size?: number;
  vibes?: string[];
}

export interface TilesSearchResponse {
  tiles: Tile[];
  tiles_request_id?: string | null;
  request_id?: string | null;
  summary?: Record<string, unknown> | null;
}

export interface SessionTripContext {
  id: number;
  origin?: string | null;
  destination_hint?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  budget_bucket?: string | null;
  group_size?: number | null;
  vibes?: string[];
  raw_prompt?: string | null;
}

export interface SessionStateResponse {
  session_id: string;
  session_exists: boolean;
  trip_context?: SessionTripContext | null;
  branches: PlanBranch[];
  primary_branch_id?: string | null;
  tiles: Tile[];
  tiles_request_id?: string | null;
}
