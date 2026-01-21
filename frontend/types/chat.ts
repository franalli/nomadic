// frontend/types/chat.ts
type ChatRole = 'user' | 'assistant';

// Message classification for collapse eligibility
export type MessageClassification = 'constraint' | 'preference' | 'question' | 'meta';

// Ack status from backend
export type AckStatus = 'pending' | 'applied' | 'partial' | 'no_change' | 'needs_clarification' | 'failed';

// Detailed update info
export interface AckUpdate {
  field: string;  // Canonical UI key (e.g., "destination", "origin", "dates")
  to: string;     // New value (human-readable)
  from_value?: string;  // Previous value if overwritten
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  // Collapsible message fields
  classification?: MessageClassification;
  ackStatus?: AckStatus;
  ackUpdates?: AckUpdate[];
  collapsed?: boolean;
  pinned?: boolean;
  summaryText?: string;
  createdAt?: string;
  ackAt?: string;
}
