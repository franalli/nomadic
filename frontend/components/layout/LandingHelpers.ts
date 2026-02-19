import type { DocumentTripInputs } from '@/types/document';

// Receipt data type for showing "Updated: X, Y · Undo" after freeform extraction
export interface ChangeReceiptData {
  type: 'partial' | 'updated' | 'reverted';
  fields: string[];
  canUndo: boolean;
}

// Topic keywords for detecting specialist topics from user messages
// Matches backend orchestrator.py TOPIC_KEYWORDS
export const TOPIC_KEYWORDS: Record<string, string[]> = {
  diving: ['dive', 'diving', 'scuba', 'snorkel', 'reef'],
  hiking: ['hike', 'hiking', 'trek', 'trail', 'mountain'],
  skiing: ['ski', 'skiing', 'snowboard', 'piste'],
  cycling: ['bike', 'cycling', 'bicycle'],
  boating: ['sail', 'boat', 'yacht', 'kayak'],
};

export const RESET_BUTTON_COOLDOWN_MS = 2500;

/**
 * Detect specialist topics from user message text.
 * Used for optimistic UI - shows placeholder AgentCards before backend responds.
 */
export function detectTopicsFromMessage(message: string): string[] {
  const lower = message.toLowerCase();
  return Object.entries(TOPIC_KEYWORDS)
    .filter(([, keywords]) => keywords.some((k) => lower.includes(k)))
    .map(([topic]) => topic);
}

// Helper to detect which trip input fields changed between two states
export function detectChangedFieldNames(
  oldInputs: DocumentTripInputs | null,
  newInputs: DocumentTripInputs | null
): string[] {
  if (!newInputs) return [];

  const changed: string[] = [];

  // Compare core fields
  if (oldInputs?.origin !== newInputs.origin && newInputs.origin) {
    changed.push('origin');
  }
  if (oldInputs?.destination !== newInputs.destination && newInputs.destination) {
    changed.push('destination');
  }
  if (oldInputs?.start_date !== newInputs.start_date && newInputs.start_date) {
    changed.push('start_date');
  }
  if (oldInputs?.end_date !== newInputs.end_date && newInputs.end_date) {
    changed.push('end_date');
  }
  if (oldInputs?.budget !== newInputs.budget && newInputs.budget != null) {
    changed.push('budget');
  }
  if (oldInputs?.adults !== newInputs.adults && newInputs.adults != null) {
    changed.push('adults');
  }
  if (oldInputs?.children !== newInputs.children && newInputs.children != null) {
    changed.push('children');
  }

  return changed;
}
