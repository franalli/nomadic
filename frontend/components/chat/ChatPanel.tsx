// frontend/components/ChatPanel.tsx
'use client';

import { ArrowUp, ChevronDown, Compass } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';

import { API_BASE } from '@/lib/api';
import { getOrCreateSessionId } from '@/lib/session';
import type { PlanRequest, PlanResponse } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type { PlanBranch, TripInputs } from '@/types/plan';
import type { Tile } from '@/types/tile';

const CHAT_HISTORY_KEY = 'chat_history';
const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    id: 'm0',
    role: 'assistant',
    content:
      "Tell me about your trip: where you're headed, where you're leaving from, dates, vibes, and how many travelers are going.",
  },
];

const getChatStorageKey = (sessionId: string) => `${CHAT_HISTORY_KEY}:${sessionId}`;

const parseStoredMessages = (raw: string | null): ChatMessage[] | null => {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const isValid = parsed.every(
      (msg) =>
        msg &&
        typeof msg.id === 'string' &&
        (msg.role === 'user' || msg.role === 'assistant') &&
        typeof msg.content === 'string'
    );
    return isValid ? (parsed as ChatMessage[]) : null;
  } catch (error) {
    console.error('Failed to parse stored chat history', error);
    return null;
  }
};

const loadStoredMessages = (sessionId: string): ChatMessage[] | null => {
  if (typeof window === 'undefined' || !sessionId) return null;
  const raw = window.localStorage.getItem(getChatStorageKey(sessionId));
  return parseStoredMessages(raw);
};

interface ChatPanelProps {
  tripContextId: number | null;
  selectedBranchId: string | null;
  tripInputs?: TripInputs | null;
  onChatTriggered?: () => void;
  onHasUserMessage?: (has: boolean) => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: PlanBranch[];
    tiles: Tile[];
    primaryBranchId: string | null;
    tilesRequestId: string | null;
    tripInputs?: TripInputs | null;
  }) => void;
  tripDetails?: {
    content: ReactNode;
    missingFields?: string[];
  };
  /** When true, the panel will try to fill available height */
  fullHeight?: boolean;
  /** When true, branches have been generated */
  hasBranches?: boolean;
}

type PlanStreamEvent =
  | {
      event: 'assistant_message';
      message_id: string;
      delta: string;
      is_final?: boolean;
      follow_up_question?: string | null;
    }
  | {
      event: 'plan_update';
      trip_context_id?: number | null;
      branches: PlanBranch[];
      primary_branch_id?: string | null;
      assistant_message_id?: string | null;
      trip_inputs?: TripInputs | null;
    }
  | {
      event: 'tiles_update';
      tiles: Tile[];
      tiles_request_id?: string | null;
      summary?: Record<string, unknown> | null;
    }
  | {
      event: 'complete';
      response: PlanResponse;
    }
  | {
      event: 'error';
      message: string;
    };

const summariseBranches = (branches: PlanBranch[]): string => {
  if (!branches.length) {
    return 'I could not settle on clear directions yet, but here are some starter booking options.';
  }

  const lines = branches.map((branch, idx) => {
    const label = `${idx + 1}. ${branch.label} (${branch.destination})`;
    return branch.description ? `${label}\n   ${branch.description}` : label;
  });

  return ['Here are a few trip directions I’d consider:', ...lines].join('\n\n');
};

export function ChatPanel(props: ChatPanelProps) {
  const { onHasUserMessage } = props;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>(DEFAULT_MESSAGES);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [detailsCollapsed, setDetailsCollapsed] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasUserMessage = messages.some((msg) => msg.role === 'user');
  const showTripDetails = Boolean(props.tripDetails) && hasUserMessage;
  const panelHeightClass = props.fullHeight
    ? 'h-full'
    : hasUserMessage
      ? 'min-h-[360px] max-h-[620px]'
      : 'min-h-[220px] max-h-[320px]';

  const scrollToBottom = useCallback(() => {
    const node = scrollContainerRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    // Ensure scroll happens after layout updates
    requestAnimationFrame(() => {
      if (node) node.scrollTop = node.scrollHeight;
    });
  }, []);

  useEffect(() => {
    onHasUserMessage?.(hasUserMessage);
  }, [hasUserMessage, onHasUserMessage]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (!sessionId || typeof window === 'undefined') return;
    const stored = loadStoredMessages(sessionId);
    if (stored) {
      setMessages(stored);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId || typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(getChatStorageKey(sessionId), JSON.stringify(messages));
    } catch (error) {
      console.error('Failed to persist chat history', error);
    }
  }, [messages, sessionId]);

  useEffect(() => {
    // Defer session id creation until after mount to avoid SSR/client mismatches.
    const id = getOrCreateSessionId();
    setSessionId(id);
    const stored = loadStoredMessages(id);
    if (stored) {
      setMessages(stored);
    }
  }, []);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    props.onChatTriggered?.();

    const userMessage: ChatMessage = {
      id: `u_${Date.now()}`,
      role: 'user',
      content: trimmed,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setTimeout(() => inputRef.current?.focus(), 0);
    setIsLoading(true);

    try {
      const body: PlanRequest = {
        message: trimmed,
      };

      const activeSessionId = sessionId ?? getOrCreateSessionId();
      if (!sessionId) {
        setSessionId(activeSessionId);
      }
      if (activeSessionId) {
        body.session_id = activeSessionId;
      }
      if (props.tripContextId != null) {
        body.trip_context_id = props.tripContextId;
      }
      if (props.tripInputs) {
        body.trip_inputs = props.tripInputs;
      }

      const res = await fetch(`${API_BASE}/v1/plan?stream=true`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Plan failed: ${res.status}`);
      }

      const handlePlanResult = (data: PlanResponse) => {
        props.onPlanResult({
          tripContextId: data.trip_context_id ?? null,
          branches: data.branches,
          tiles: data.tiles,
          primaryBranchId:
            data.primary_branch_id ??
            data.branches[0]?.id ??
            props.selectedBranchId ??
            null,
          tilesRequestId: data.tiles_request_id ?? null,
          tripInputs: data.trip_inputs ?? null,
        });
      };

      const consumeStream = async () => {
        const stream = res.body;
        if (!stream || typeof stream.getReader !== 'function') {
          const fallback: PlanResponse = await res.json();
          handlePlanResult(fallback);
          const assistantText =
            fallback.assistant_message || summariseBranches(fallback.branches);
          const msgId = fallback.assistant_message_id ?? `a_${Date.now()}`;

          // Split into sentences for separate bubbles
          const sentences = assistantText
            .split(/(?<=[.!?])\s+/)
            .filter((s) => s.trim().length > 0);
          if (fallback.follow_up_question) {
            sentences.push(fallback.follow_up_question);
          }

          const newMessages: ChatMessage[] = sentences.map((s, idx) => ({
            id: `${msgId}_s${idx}`,
            role: 'assistant' as const,
            content: s,
          }));
          setMessages((prev) => [...prev, ...newMessages]);
          return;
        }

        const reader = stream.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let sawComplete = false;
        let activeAssistantId: string | null = null;
        let latestPlan: Partial<PlanResponse> = {};
        let sentenceIndex = 0;
        let baseMessageId: string | null = null;

        const emitPlanSnapshot = () => {
          const snapshot: PlanResponse = {
            branches: latestPlan.branches ?? [],
            tiles: latestPlan.tiles ?? [],
            trip_context_id: latestPlan.trip_context_id ?? null,
            primary_branch_id: latestPlan.primary_branch_id ?? null,
            tiles_request_id: latestPlan.tiles_request_id ?? null,
            tiles_summary: latestPlan.tiles_summary ?? null,
            assistant_message: latestPlan.assistant_message ?? null,
            assistant_message_id: latestPlan.assistant_message_id ?? null,
            follow_up_question: latestPlan.follow_up_question ?? null,
            trip_inputs: latestPlan.trip_inputs ?? null,
          };
          handlePlanResult(snapshot);
        };

        const ensureAssistantMessage = (messageId: string) => {
          if (!baseMessageId) {
            baseMessageId = messageId;
          }
          const currentId = `${baseMessageId}_s${sentenceIndex}`;
          if (activeAssistantId === currentId) return;
          activeAssistantId = currentId;
          setMessages((prev) => {
            const exists = prev.some((msg) => msg.id === currentId);
            if (exists) return prev;
            return [...prev, { id: currentId, role: 'assistant', content: '' }];
          });
        };

        const appendAssistantDelta = (
          _messageId: string,
          delta: string,
          followUp?: string | null
        ) => {
          // We use activeAssistantId which includes sentence index
          const currentId = activeAssistantId;
          if (!currentId) return;

          // Skip empty deltas
          if (!delta) return;

          setMessages((prev) => {
            const updated = prev.map((msg) => {
              if (msg.id !== currentId) return msg;
              return { ...msg, content: `${msg.content || ''}${delta}` };
            });
            return updated;
          });

          // Check if we completed a sentence and need to start a new bubble
          setMessages((prev) => {
            const currentMsg = prev.find((msg) => msg.id === currentId);
            if (!currentMsg) return prev;

            const content = currentMsg.content;
            // Match sentence ending followed by space (indicating more content coming)
            const sentenceEndMatch = content.match(/^(.+?[.!?])\s+(.+)$/s);

            if (sentenceEndMatch) {
              const completedSentence = sentenceEndMatch[1].trim();
              const remainder = sentenceEndMatch[2].trim();

              // Only split if both parts are non-empty
              if (completedSentence && remainder) {
                sentenceIndex++;
                const newId = `${baseMessageId}_s${sentenceIndex}`;
                activeAssistantId = newId;

                return [
                  ...prev.map((msg) =>
                    msg.id === currentId ? { ...msg, content: completedSentence } : msg
                  ),
                  { id: newId, role: 'assistant' as const, content: remainder },
                ];
              }
            }
            return prev;
          });

          // Handle follow-up question by adding it as a new bubble
          if (followUp && followUp.trim().length > 0) {
            sentenceIndex++;
            const followUpId = `${baseMessageId}_s${sentenceIndex}`;
            setMessages((prev) => [
              ...prev,
              { id: followUpId, role: 'assistant' as const, content: followUp.trim() },
            ]);
          }
        };

        const applyCompleteSnapshot = (plan: PlanResponse) => {
          handlePlanResult(plan);
          // The streaming already handled creating sentence bubbles,
          // but we need to ensure the final state is correct.
          // Split the complete message into sentences and reconcile.
          if (plan.assistant_message_id && plan.assistant_message) {
            const msgId = plan.assistant_message_id;
            // Split by sentence-ending punctuation followed by whitespace
            // Filter out empty strings and whitespace-only strings
            const sentences = plan.assistant_message
              .split(/(?<=[.!?])\s+/)
              .map((s) => s.trim())
              .filter((s) => s.length > 0);

            // Only add follow_up_question if it's not empty and not already included
            if (
              plan.follow_up_question &&
              plan.follow_up_question.trim().length > 0 &&
              !sentences.some((s) => s === plan.follow_up_question?.trim())
            ) {
              sentences.push(plan.follow_up_question.trim());
            }

            // Only update if we have valid sentences
            if (sentences.length > 0) {
              setMessages((prev) => {
                // Remove any existing messages with this base ID (from streaming)
                const filtered = prev.filter((msg) => !msg.id.startsWith(`${msgId}_s`));
                // Add the final split sentences
                const newMessages: ChatMessage[] = sentences.map((s, idx) => ({
                  id: `${msgId}_s${idx}`,
                  role: 'assistant' as const,
                  content: s,
                }));
                return [...filtered, ...newMessages];
              });
            }
          }
        };

        const handleEvent = (payload: PlanStreamEvent) => {
          switch (payload.event) {
            case 'assistant_message': {
              const messageId =
                payload.message_id || activeAssistantId || `a_${Date.now()}`;
              ensureAssistantMessage(messageId);
              appendAssistantDelta(
                messageId,
                payload.delta,
                payload.is_final ? payload.follow_up_question : undefined
              );
              break;
            }
            case 'plan_update': {
              latestPlan = {
                ...latestPlan,
                trip_context_id: payload.trip_context_id ?? latestPlan.trip_context_id,
                branches: payload.branches ?? latestPlan.branches ?? [],
                primary_branch_id:
                  payload.primary_branch_id ?? latestPlan.primary_branch_id,
                assistant_message_id:
                  payload.assistant_message_id ?? latestPlan.assistant_message_id,
                trip_inputs: payload.trip_inputs ?? latestPlan.trip_inputs ?? null,
              };
              if (payload.assistant_message_id) {
                ensureAssistantMessage(payload.assistant_message_id);
              }
              emitPlanSnapshot();
              break;
            }
            case 'tiles_update': {
              latestPlan = {
                ...latestPlan,
                tiles: payload.tiles ?? latestPlan.tiles ?? [],
                tiles_request_id: payload.tiles_request_id ?? latestPlan.tiles_request_id,
                tiles_summary: payload.summary ?? latestPlan.tiles_summary,
              };
              emitPlanSnapshot();
              break;
            }
            case 'complete':
              sawComplete = true;
              applyCompleteSnapshot(payload.response);
              break;
            case 'error':
              throw new Error(payload.message);
            default:
              break;
          }
        };

        let reading = true;
        while (reading) {
          const { value, done } = await reader.read();
          if (done) {
            reading = false;
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          let newlineIndex = buffer.indexOf('\n');
          while (newlineIndex >= 0) {
            const raw = buffer.slice(0, newlineIndex).trim();
            buffer = buffer.slice(newlineIndex + 1);
            if (raw) {
              const parsed = JSON.parse(raw) as PlanStreamEvent;
              handleEvent(parsed);
            }
            newlineIndex = buffer.indexOf('\n');
          }
        }

        if (buffer.trim()) {
          const parsed = JSON.parse(buffer.trim()) as PlanStreamEvent;
          handleEvent(parsed);
        }

        if (!sawComplete) {
          throw new Error('Plan stream ended before completion.');
        }
      };

      await consumeStream();
    } catch (error) {
      console.error('Failed to plan trip', error);
      const assistantMessage: ChatMessage = {
        id: `a_err_${Date.now()}`,
        role: 'assistant',
        content:
          'I ran into an error planning this trip. Try again in a moment or tweak your message.',
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div
      className={`bg-card/90 text-foreground flex ${panelHeightClass} min-h-0 flex-col gap-3 rounded-2xl border border-white/20 p-4 shadow-xl backdrop-blur transition-[min-height,max-height] duration-300`}
    >
      <div className="flex items-center justify-between">
        <div className="text-muted-foreground text-[11px] font-semibold uppercase tracking-wide">
          Travel planner
        </div>
      </div>

      {showTripDetails ? (
        <div className="rounded-xl bg-white px-2 py-1.5">
          <button
            type="button"
            className="flex w-full items-center justify-start gap-2 text-left"
            onClick={() => setDetailsCollapsed((prev) => !prev)}
          >
            <span className="text-muted-foreground text-[11px] font-semibold uppercase leading-none tracking-wide">
              Trip details
            </span>
            <ChevronDown
              className={`text-muted-foreground h-4 w-4 transition-transform ${
                detailsCollapsed ? '-rotate-90' : ''
              }`}
            />
          </button>
          <div
            className={`grid transition-[grid-template-rows] duration-300 ease-in-out ${
              detailsCollapsed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]'
            }`}
          >
            <div className="overflow-hidden pt-2">{props.tripDetails?.content}</div>
          </div>
        </div>
      ) : null}

      <div
        ref={scrollContainerRef}
        className="no-scrollbar min-h-0 flex-1 space-y-2 overflow-y-auto text-sm"
      >
        {messages
          .filter((m) => m.content && m.content.trim().length > 0)
          .map((m) => (
            <div key={m.id} className={m.role === 'user' ? 'text-right' : 'text-left'}>
              <div
                className={
                  m.role === 'user'
                    ? 'bg-primary text-primary-foreground inline-block max-w-[80%] rounded-2xl px-3 py-2 shadow-sm'
                    : 'border-border/60 bg-muted text-foreground inline-block max-w-[80%] rounded-2xl border px-3 py-2'
                }
              >
                {m.content}
              </div>
            </div>
          ))}
      </div>

      <form onSubmit={handleSubmit} className="relative">
        <input
          ref={inputRef}
          className="border-input bg-muted/60 text-foreground placeholder:text-muted-foreground focus-visible:ring-primary focus-visible:ring-offset-card w-full rounded-xl border px-3 py-2 pr-20 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
          placeholder={
            props.hasBranches
              ? 'Keep chatting to plan'
              : 'Chat with me to design your perfect trip'
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button
          type="submit"
          className="bg-primary text-primary-foreground hover:bg-primary/90 absolute right-1 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-lg px-3 py-1 text-sm font-semibold transition-colors disabled:opacity-60"
          disabled={isLoading}
        >
          {isLoading ? (
            <Compass className="text-accent compass-spin h-4 w-4" />
          ) : (
            <ArrowUp className="h-4 w-4" />
          )}
        </button>
      </form>
    </div>
  );
}
