// frontend/types/api.ts
// PlanRequest is simplified - all state flows through the document
// session_id is now sent via HttpOnly cookie, not in the request body
export interface PlanRequest {
  message: string; // The user's chat message
  timezone?: string; // IANA timezone (e.g., "Europe/Rome") for "today" calculation
}
