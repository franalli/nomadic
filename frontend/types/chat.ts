// frontend/types/chat.ts
import type { DocumentTripInputs } from '@/types/document';

export type ChatRole = 'user' | 'assistant' | 'system';

// Display mode for message rendering
export type MessageDisplayMode = 'full' | 'ack_line' | 'collapsed_summary';

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

// Phase for visual distinction between Setup and Plan conversations
export type ChatPhase = 'setup' | 'plan';

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  // Display mode for rendering (full message, ack line, or collapsed summary)
  displayMode?: MessageDisplayMode;
  // Phase this message belongs to - enables visual distinction (Setup = faded, Plan = normal)
  phase?: ChatPhase;
  // Collapsible message fields
  classification?: MessageClassification;
  ackStatus?: AckStatus;
  ackUpdates?: AckUpdate[];
  collapsed?: boolean;
  pinned?: boolean;
  summaryText?: string;
  createdAt?: string;
  ackAt?: string;
  // Configuration snapshot for collapsed setup summary (audit trail)
  tripInputsSnapshot?: DocumentTripInputs;
  executedTopicsSnapshot?: string[];
}
