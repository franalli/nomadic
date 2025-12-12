// frontend/types/api.ts
// Re-export PlanRequest from generated types (auto-generated from backend schemas)
// Run `npm run types:generate` after schema changes to keep in sync
export type { components } from './generated';

export type PlanRequest = import('./generated').components['schemas']['PlanRequest'];

// Manual mirror of backend/app/schemas.py: GraphPlanRequest
export type GraphPlanRequest = {
	message: string;
	trip_inputs?: Record<string, unknown>;
	session_state?: Record<string, unknown> | null;
	document_id?: string | null;
	expected_version?: number | null;
	thread_id?: string | null;
	reset?: boolean;
};
