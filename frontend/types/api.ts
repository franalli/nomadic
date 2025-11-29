import type { PlanDocumentResponse } from '@/types/document';

// frontend/types/api.ts
// PlanRequest is simplified - all state flows through the document
export interface PlanRequest {
  session_id: string; // Required - identifies the planning session
  message: string; // The user's chat message
}

// PlanResponse is now PlanDocumentResponse from document.ts
export type PlanResponse = PlanDocumentResponse;
