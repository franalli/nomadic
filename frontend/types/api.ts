import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

// frontend/types/api.ts
export interface PlanRequest {
  user_id?: string;
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
  primary_branch_id?: string | null;
  tiles_request_id?: string | null;
  tiles_summary?: Record<string, unknown> | null;
}
