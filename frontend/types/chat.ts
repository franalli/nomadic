// frontend/types/chat.ts

export type ChatRole = 'user' | 'assistant' | 'system';

// Display mode for message rendering
export type MessageDisplayMode = 'full' | 'ack_line';

// Message classification for collapse eligibility
export type MessageClassification = 'constraint' | 'preference' | 'question' | 'meta';

// Ack status from backend
export type AckStatus = 'pending' | 'applied' | 'partial' | 'no_change' | 'needs_clarification' | 'failed' | 'rejected';

// Detailed update info
export interface AckUpdate {
  field: string;  // Canonical UI key (e.g., "destination", "origin", "dates")
  to: string;     // New value (human-readable)
  from_value?: string;  // Previous value if overwritten
}

// Phase for visual distinction (used by SystemReceipt)
export type ChatPhase = 'setup' | 'plan';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  displayMode?: MessageDisplayMode;
  classification?: MessageClassification;
  ackStatus?: AckStatus;
  ackUpdates?: AckUpdate[];
  pinned?: boolean;
  createdAt?: string;
  ackAt?: string;
}
