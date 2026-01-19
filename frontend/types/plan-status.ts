/**
 * Legacy Plan Status Model
 *
 * @deprecated Use PlanState from plan-envelope.ts instead.
 * This type is kept for backwards compatibility during migration.
 */

export type SpecialistKey = 'flights' | 'hotels' | 'activities' | 'transport';
export type SpecialistState = 'queued' | 'running' | 'done' | 'error';

export interface SpecialistStatus {
  key: SpecialistKey;
  state: SpecialistState;
}

export interface PlanStatus {
  /** Current phase */
  phase: 'needs_input' | 'ready' | 'updating' | 'error';
  /** Missing required fields */
  missing: string[];
  /** Constraints changed since last successful build */
  dirty: boolean;
  /** Active specialist statuses */
  activeSpecialists: SpecialistStatus[];
  /** Last successful update timestamp */
  lastUpdatedAt: number | null;
  /** Current run ID for race safety */
  activeRunId: string | null;
}

/**
 * Initial/default plan status
 */
export const INITIAL_PLAN_STATUS: PlanStatus = {
  phase: 'needs_input',
  missing: [],
  dirty: false,
  activeSpecialists: [],
  lastUpdatedAt: null,
  activeRunId: null,
};
