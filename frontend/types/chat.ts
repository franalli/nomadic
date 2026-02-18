// frontend/types/chat.ts

import type { AckStatus, AckUpdate } from '@/types/plan-envelope';

export type { AckStatus, AckUpdate };

type ChatRole = 'user' | 'assistant' | 'system';

// Display mode for message rendering
type MessageDisplayMode = 'full' | 'ack_line';

// Message classification for collapse eligibility
type MessageClassification = 'constraint' | 'preference' | 'question' | 'meta';

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
