/**
 * Chat State Machine Hook
 *
 * Consolidates ChatPanel's 14+ useState hooks into a single reducer-based
 * state machine. This provides:
 * - Single source of truth for chat state
 * - Explicit state transitions via actions
 * - Easier testing and debugging
 * - Predictable state updates
 */

import { useCallback, useReducer, useRef } from 'react';

import type { ChatMessage } from '@/types/chat';

// =============================================================================
// Types
// =============================================================================

export type ChatMode = 'idle' | 'loading' | 'streaming' | 'error';

export type StrategyStatus = {
  active: boolean;
  stage: number;
  tier: 'outline' | 'section' | 'full';
  topic: 'hiking' | 'skiing' | 'diving' | 'cycling' | 'boating';
  estimatedDurationMs: number;
  startTime: number;
} | null;

export type ChatState = {
  // Core chat state
  mode: ChatMode;
  messages: ChatMessage[];
  input: string;
  suggestedResponses: string[];

  // Loading states
  isLoadingHistory: boolean;
  streamingMessageId: string | null;
  hasReceivedFirstToken: boolean;

  // Strategy progress
  strategyStatus: StrategyStatus;

  // UI state
  isMobile: boolean;
  tripDetailsOpen: boolean;
  hasShownHint: boolean;

  // Generation state
  generateTriggered: boolean;
  readyMessageShown: boolean;

  // Session persistence
  sessionState: Record<string, unknown> | null;
};

// =============================================================================
// Actions
// =============================================================================

export type ChatAction =
  // Core message actions
  | { type: 'SET_MESSAGES'; payload: ChatMessage[] }
  | { type: 'ADD_MESSAGE'; payload: ChatMessage }
  | { type: 'UPDATE_MESSAGE'; payload: { id: string; updates: Partial<ChatMessage> } }
  | { type: 'REMOVE_MESSAGES'; payload: { filter: (msg: ChatMessage) => boolean } }
  | { type: 'SET_INPUT'; payload: string }
  | { type: 'SET_SUGGESTIONS'; payload: string[] }

  // Loading state actions
  | { type: 'START_LOADING' }
  | { type: 'STOP_LOADING' }
  | { type: 'SET_LOADING_HISTORY'; payload: boolean }
  | { type: 'START_STREAMING'; payload: string } // payload is streamingMessageId
  | { type: 'STOP_STREAMING' }
  | { type: 'RECEIVE_FIRST_TOKEN' }
  | { type: 'APPEND_TOKEN'; payload: { id: string; token: string } }
  | { type: 'INTERRUPT_STREAM' }

  // Strategy progress actions
  | { type: 'SET_STRATEGY_STATUS'; payload: StrategyStatus }
  | { type: 'CLEAR_STRATEGY_STATUS' }

  // UI actions
  | { type: 'SET_MOBILE'; payload: boolean }
  | { type: 'SET_TRIP_DETAILS_OPEN'; payload: boolean }
  | { type: 'SET_HINT_SHOWN' }

  // Generation actions
  | { type: 'TRIGGER_GENERATE' }
  | { type: 'RESET_GENERATE_STATE' }
  | { type: 'SET_READY_MESSAGE_SHOWN'; payload: boolean }

  // Session actions
  | { type: 'SET_SESSION_STATE'; payload: Record<string, unknown> | null }

  // Compound actions for common patterns
  | { type: 'COMPLETE_RESPONSE'; payload: {
      sessionState: Record<string, unknown> | null;
      suggestedResponses: string[];
    }}
  | { type: 'HANDLE_ERROR'; payload: { streamingMessageId: string; errorMessage: string } }
  | { type: 'RESET_FOR_FRESH_START' };

// =============================================================================
// Default Messages
// =============================================================================

const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    id: 'm0',
    role: 'assistant',
    content:
      "Hey there! ✈️ I'm excited to help you plan an amazing trip! Where are you dreaming of going?",
  },
];

// =============================================================================
// Initial State
// =============================================================================

export const initialChatState: ChatState = {
  mode: 'idle',
  messages: DEFAULT_MESSAGES,
  input: '',
  suggestedResponses: [],
  isLoadingHistory: true,
  streamingMessageId: null,
  hasReceivedFirstToken: false,
  strategyStatus: null,
  isMobile: false,
  tripDetailsOpen: true,
  hasShownHint: false,
  generateTriggered: false,
  readyMessageShown: false,
  sessionState: null,
};

// =============================================================================
// Reducer
// =============================================================================

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    // Core message actions
    case 'SET_MESSAGES':
      return { ...state, messages: action.payload };

    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.payload] };

    case 'UPDATE_MESSAGE':
      return {
        ...state,
        messages: state.messages.map((msg) =>
          msg.id === action.payload.id ? { ...msg, ...action.payload.updates } : msg
        ),
      };

    case 'REMOVE_MESSAGES':
      return {
        ...state,
        messages: state.messages.filter(action.payload.filter),
      };

    case 'SET_INPUT':
      return { ...state, input: action.payload };

    case 'SET_SUGGESTIONS':
      return { ...state, suggestedResponses: action.payload };

    // Loading state actions
    case 'START_LOADING':
      return { ...state, mode: 'loading' };

    case 'STOP_LOADING':
      return { ...state, mode: 'idle' };

    case 'SET_LOADING_HISTORY':
      return { ...state, isLoadingHistory: action.payload };

    case 'START_STREAMING':
      return {
        ...state,
        mode: 'streaming',
        streamingMessageId: action.payload,
        hasReceivedFirstToken: false,
        messages: [
          ...state.messages,
          { id: action.payload, role: 'assistant', content: '' },
        ],
      };

    case 'STOP_STREAMING':
      return {
        ...state,
        mode: 'idle',
        streamingMessageId: null,
        hasReceivedFirstToken: false,
      };

    case 'RECEIVE_FIRST_TOKEN':
      return { ...state, hasReceivedFirstToken: true };

    case 'APPEND_TOKEN':
      return {
        ...state,
        hasReceivedFirstToken: true,
        messages: state.messages.map((msg) =>
          msg.id === action.payload.id
            ? { ...msg, content: (msg.content || '') + action.payload.token }
            : msg
        ),
      };

    case 'INTERRUPT_STREAM':
      return {
        ...state,
        mode: 'idle',
        streamingMessageId: null,
        hasReceivedFirstToken: false,
        strategyStatus: null,
        messages: state.streamingMessageId
          ? state.messages.map((msg) =>
              msg.id === state.streamingMessageId
                ? { ...msg, content: (msg.content || '') + '...[interrupted]' }
                : msg
            )
          : state.messages,
      };

    // Strategy progress actions
    case 'SET_STRATEGY_STATUS':
      return { ...state, strategyStatus: action.payload };

    case 'CLEAR_STRATEGY_STATUS':
      return { ...state, strategyStatus: null };

    // UI actions
    case 'SET_MOBILE':
      return { ...state, isMobile: action.payload };

    case 'SET_TRIP_DETAILS_OPEN':
      return { ...state, tripDetailsOpen: action.payload };

    case 'SET_HINT_SHOWN':
      return { ...state, hasShownHint: true };

    // Generation actions
    case 'TRIGGER_GENERATE':
      return { ...state, generateTriggered: true };

    case 'RESET_GENERATE_STATE':
      return {
        ...state,
        generateTriggered: false,
        readyMessageShown: false,
      };

    case 'SET_READY_MESSAGE_SHOWN':
      return { ...state, readyMessageShown: action.payload };

    // Session actions
    case 'SET_SESSION_STATE':
      return { ...state, sessionState: action.payload };

    // Compound actions for common patterns
    case 'COMPLETE_RESPONSE':
      return {
        ...state,
        mode: 'idle',
        streamingMessageId: null,
        hasReceivedFirstToken: false,
        strategyStatus: null,
        sessionState: action.payload.sessionState,
        suggestedResponses: action.payload.suggestedResponses,
      };

    case 'HANDLE_ERROR':
      return {
        ...state,
        mode: 'error',
        streamingMessageId: null,
        hasReceivedFirstToken: false,
        strategyStatus: null,
        messages: state.messages.map((msg) =>
          msg.id === action.payload.streamingMessageId
            ? {
                ...msg,
                id: `a_err_${Date.now()}`,
                content: action.payload.errorMessage,
              }
            : msg
        ),
      };

    case 'RESET_FOR_FRESH_START':
      return {
        ...initialChatState,
        isLoadingHistory: false, // Don't reload history on fresh start
        isMobile: state.isMobile, // Preserve mobile detection
      };

    default:
      return state;
  }
}

// =============================================================================
// Hook
// =============================================================================

export function useChatStateMachine() {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const abortStreamRef = useRef<(() => void) | null>(null);

  // Computed values
  const isLoading = state.mode === 'loading' || state.mode === 'streaming';
  const hasUserMessage = state.messages.some((msg) => msg.role === 'user');
  const showTypingIndicator =
    isLoading && !state.hasReceivedFirstToken && !state.strategyStatus?.active;
  const showStrategyProgress =
    isLoading && !state.hasReceivedFirstToken && state.strategyStatus?.active;

  // Actions as stable callbacks
  const setMessages = useCallback((messages: ChatMessage[]) => {
    dispatch({ type: 'SET_MESSAGES', payload: messages });
  }, []);

  const addMessage = useCallback((message: ChatMessage) => {
    dispatch({ type: 'ADD_MESSAGE', payload: message });
  }, []);

  const updateMessage = useCallback((id: string, updates: Partial<ChatMessage>) => {
    dispatch({ type: 'UPDATE_MESSAGE', payload: { id, updates } });
  }, []);

  const setInput = useCallback((input: string) => {
    dispatch({ type: 'SET_INPUT', payload: input });
  }, []);

  const setSuggestions = useCallback((suggestions: string[]) => {
    dispatch({ type: 'SET_SUGGESTIONS', payload: suggestions });
  }, []);

  const setLoadingHistory = useCallback((loading: boolean) => {
    dispatch({ type: 'SET_LOADING_HISTORY', payload: loading });
  }, []);

  const startStreaming = useCallback((messageId: string) => {
    dispatch({ type: 'START_STREAMING', payload: messageId });
  }, []);

  const appendToken = useCallback((id: string, token: string) => {
    dispatch({ type: 'APPEND_TOKEN', payload: { id, token } });
  }, []);

  const interruptStream = useCallback(() => {
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }
    dispatch({ type: 'INTERRUPT_STREAM' });
  }, []);

  const setStrategyStatus = useCallback((status: StrategyStatus) => {
    dispatch({ type: 'SET_STRATEGY_STATUS', payload: status });
  }, []);

  const setMobile = useCallback((mobile: boolean) => {
    dispatch({ type: 'SET_MOBILE', payload: mobile });
  }, []);

  const setTripDetailsOpen = useCallback((open: boolean) => {
    dispatch({ type: 'SET_TRIP_DETAILS_OPEN', payload: open });
  }, []);

  const setHintShown = useCallback(() => {
    dispatch({ type: 'SET_HINT_SHOWN' });
  }, []);

  const triggerGenerate = useCallback(() => {
    dispatch({ type: 'TRIGGER_GENERATE' });
  }, []);

  const resetGenerateState = useCallback(() => {
    dispatch({ type: 'RESET_GENERATE_STATE' });
  }, []);

  const setReadyMessageShown = useCallback((shown: boolean) => {
    dispatch({ type: 'SET_READY_MESSAGE_SHOWN', payload: shown });
  }, []);

  const completeResponse = useCallback(
    (sessionState: Record<string, unknown> | null, suggestedResponses: string[]) => {
      dispatch({
        type: 'COMPLETE_RESPONSE',
        payload: { sessionState, suggestedResponses },
      });
    },
    []
  );

  const handleError = useCallback((streamingMessageId: string, errorMessage: string) => {
    dispatch({
      type: 'HANDLE_ERROR',
      payload: { streamingMessageId, errorMessage },
    });
  }, []);

  const resetForFreshStart = useCallback(() => {
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }
    dispatch({ type: 'RESET_FOR_FRESH_START' });
  }, []);

  const removeReadyMessages = useCallback((prefix: string) => {
    dispatch({
      type: 'REMOVE_MESSAGES',
      payload: { filter: (msg) => !msg.id.startsWith(prefix) },
    });
  }, []);

  return {
    // State
    state,

    // Computed
    isLoading,
    hasUserMessage,
    showTypingIndicator,
    showStrategyProgress,

    // Refs
    abortStreamRef,

    // Actions
    setMessages,
    addMessage,
    updateMessage,
    setInput,
    setSuggestions,
    setLoadingHistory,
    startStreaming,
    appendToken,
    interruptStream,
    setStrategyStatus,
    setMobile,
    setTripDetailsOpen,
    setHintShown,
    triggerGenerate,
    resetGenerateState,
    setReadyMessageShown,
    completeResponse,
    handleError,
    resetForFreshStart,
    removeReadyMessages,
  };
}

export type UseChatStateMachineReturn = ReturnType<typeof useChatStateMachine>;
