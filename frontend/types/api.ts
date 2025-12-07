// frontend/types/api.ts
// Re-export PlanRequest from generated types (auto-generated from backend schemas)
// Run `npm run types:generate` after schema changes to keep in sync
export type { components } from './generated';

export type PlanRequest = import('./generated').components['schemas']['PlanRequest'];
