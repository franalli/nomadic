/**
 * Chat State Store
 *
 * This store manages chat messages and session state, ensuring
 * messages persist across component remounts (e.g., during layout transitions).
 *
 * Key features:
 * - Messages survive AnimatePresence layout transitions
 * - Session state persisted for conversation continuity
 * - Single history load on first access (not on every component mount)
 * - Support for message deletion with trip input rollback
 */

import { create } from 'zustand';

import { apiFetch } from '@/lib/api';
import type { ChatMessage } from '@/types/chat';

// Special message that triggers plan generation (must match backend)
export const GENERATE_PLAN_TRIGGER = 'GENERATE_PLAN_NOW';

// Default welcome message
const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    id: 'm0',
    role: 'assistant',
    content:
      "Hey there! ✈️ I'm excited to help you plan an amazing trip! Where are you dreaming of going?",
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

type ChatState = {
  // Messages
  messages: ChatMessage[];
  isLoadingHistory: boolean;
  historyLoaded: boolean;

  // Session state (for conversation continuity)
  sessionState: Record<string, unknown> | null;

  // Actions
  loadHistory: () => Promise<void>;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void;
  appendToMessage: (id: string, content: string) => void;
  updateMessageId: (oldId: string, newId: string) => void;
  filterMessages: (predicate: (msg: ChatMessage) => boolean) => void;
  removeMessagesFromId: (id: string) => void;
  setSessionState: (state: Record<string, unknown> | null) => void;
  resetChat: () => void;

  // Delete last message (calls backend and updates state)
  deleteLastMessage: () => Promise<{
    success: boolean;
    deletedCount: number;
    restoredTripInputs?: Record<string, unknown>;
    error?: string;
  }>;
};

// ─────────────────────────────────────────────────────────────────────────────
// Store
// ─────────────────────────────────────────────────────────────────────────────

export const useChatStore = create<ChatState>()((set, get) => ({
  messages: DEFAULT_MESSAGES,
  isLoadingHistory: true,
  historyLoaded: false,
  sessionState: null,

  loadHistory: async () => {
    const { historyLoaded } = get();
    if (historyLoaded) return; // Already loaded, skip

    set({ isLoadingHistory: true });

    try {
      const res = await apiFetch('/v1/chat');
      if (res.ok) {
        const data = await res.json();
        if (data.messages && data.messages.length > 0) {
          const loadedMessages: ChatMessage[] = data.messages.map(
            (m: { id: string; role: string; content: string }) => ({
              id: m.id,
              role: m.role as 'user' | 'assistant',
              // Transform any stored trigger to friendly text (handles legacy data)
              content:
                m.content === GENERATE_PLAN_TRIGGER
                  ? 'Generate my trip options'
                  : m.content,
            })
          );
          set({ messages: loadedMessages });
        }
      }
    } catch (error) {
      console.error('Failed to load chat history', error);
      // Keep default messages on error
    } finally {
      set({ isLoadingHistory: false, historyLoaded: true });
    }
  },

  setMessages: (messages) => set({ messages }),

  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
    })),

  updateMessage: (id, updates) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === id ? { ...msg, ...updates } : msg
      ),
    })),

  appendToMessage: (id, content) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === id ? { ...msg, content: (msg.content || '') + content } : msg
      ),
    })),

  updateMessageId: (oldId, newId) =>
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === oldId ? { ...msg, id: newId } : msg
      ),
    })),

  filterMessages: (predicate) =>
    set((state) => ({
      messages: state.messages.filter(predicate),
    })),

  removeMessagesFromId: (id) =>
    set((state) => {
      const idx = state.messages.findIndex((m) => m.id === id);
      if (idx === -1) return state;
      return {
        messages: state.messages.slice(0, idx),
      };
    }),

  setSessionState: (sessionState) => set({ sessionState }),

  resetChat: () =>
    set({
      messages: DEFAULT_MESSAGES,
      isLoadingHistory: false,
      historyLoaded: false,
      sessionState: null,
    }),

  deleteLastMessage: async () => {
    const { messages } = get();

    // Find the last user message
    const lastUserIdx = [...messages]
      .reverse()
      .findIndex((m) => m.role === 'user');
    if (lastUserIdx === -1) {
      return { success: false, deletedCount: 0, error: 'No user message to delete' };
    }

    const actualIdx = messages.length - 1 - lastUserIdx;

    try {
      const res = await apiFetch('/v1/chat/last', { method: 'DELETE' });

      if (!res.ok) {
        const errorText = await res.text().catch(() => 'Unknown error');
        return { success: false, deletedCount: 0, error: errorText };
      }

      const data = await res.json();

      // Remove the last user message and any assistant messages after it
      set((state) => ({
        messages: state.messages.slice(0, actualIdx),
      }));

      return {
        success: true,
        deletedCount: data.deleted_count || 1,
        restoredTripInputs: data.restored_trip_inputs,
      };
    } catch (error) {
      console.error('Failed to delete last message', error);
      return {
        success: false,
        deletedCount: 0,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  },
}));

// ─────────────────────────────────────────────────────────────────────────────
// Selector Hooks
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Get just the messages for rendering.
 */
export function useChatMessages() {
  return useChatStore((state) => state.messages);
}

/**
 * Check if chat history is loading.
 */
export function useChatLoading() {
  return useChatStore((state) => state.isLoadingHistory);
}

/**
 * Get session state for API calls.
 */
export function useChatSessionState() {
  return useChatStore((state) => state.sessionState);
}

/**
 * Check if user has sent any messages.
 */
export function useHasUserMessage() {
  return useChatStore((state) => state.messages.some((m) => m.role === 'user'));
}

/**
 * Get the last user message (for delete button visibility).
 */
export function useLastUserMessage() {
  return useChatStore((state) => {
    const userMessages = state.messages.filter((m) => m.role === 'user');
    return userMessages.length > 0 ? userMessages[userMessages.length - 1] : null;
  });
}
