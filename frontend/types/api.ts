import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

// frontend/types/api.ts
export interface PlanRequest {
  user_id?: string;
  session_id?: string;
  message: string;
  trip_context_id?: number;
}

export interface PlanResponse {
  branches: PlanBranch[];
  tiles: Tile[];
  trip_context_id?: number | null;
  primary_branch_id?: string | null;
  tiles_request_id?: string | null;
  tiles_summary?: Record<string, unknown> | null;
  assistant_message?: string | null;
  assistant_message_id?: string | null;
  follow_up_question?: string | null;
}

export interface SessionTripContext {
  id: number;
  raw_prompt?: string | null;
}

export interface TilesSearchRequest {
  user_id?: string;
  branch_id?: number;
  session_id?: string;
  trip_context_id?: number;
  destination?: string;
  destination_hint?: string;
}

export interface TilesSearchResponse {
  tiles: Tile[];
  tiles_request_id?: string | null;
  request_id?: string | null;
  summary?: Record<string, unknown> | null;
}

export interface SessionSnapshotBranch {
  id: number;
  label: string;
  description: string;
  destination: string;
}

export interface SessionSnapshot {
  branches: SessionSnapshotBranch[];
  primary_branch_id?: number | null;
  tiles: Tile[];
  trip_context?: SessionTripContext | null;
}
