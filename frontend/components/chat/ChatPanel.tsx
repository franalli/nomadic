// frontend/components/ChatPanel.tsx
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { Loader2 } from 'lucide-react';

import { API_BASE } from '@/lib/api';
import { getOrCreateSessionId } from '@/lib/session';
import type { PlanRequest, PlanResponse } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type { PlanBranch, TripInputs } from '@/types/plan';
import type { Tile } from '@/types/tile';

interface ChatPanelProps {
  tripContextId: number | null;
  selectedBranchId: string | null;
  tripInputs?: TripInputs | null;
  onChatTriggered?: () => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: PlanBranch[];
    tiles: Tile[];
    primaryBranchId: string | null;
    tilesRequestId: string | null;
    tripInputs?: TripInputs | null;
  }) => void;
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
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'm0',
      role: 'assistant',
      content:
        "Tell me about your trip: where you're headed, where you're leaving from, dates, vibes, and how many travelers are going.",
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  const scrollToBottom = useCallback(() => {
    const node = scrollContainerRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

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
    setIsLoading(true);

    try {
      const sessionId = getOrCreateSessionId();
      const body: PlanRequest = {
        message: trimmed,
      };

      if (sessionId) {
        body.session_id = sessionId;
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
          const followUp = fallback.follow_up_question
            ? `\n\n${fallback.follow_up_question}`
            : '';
          const assistantText =
            (fallback.assistant_message || summariseBranches(fallback.branches)) +
            followUp;
          setMessages((prev) => [
            ...prev,
            {
              id: fallback.assistant_message_id ?? `a_${Date.now()}`,
              role: 'assistant',
              content: assistantText,
            },
          ]);
          return;
        }

        const reader = stream.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let sawComplete = false;
        let activeAssistantId: string | null = null;
        let latestPlan: Partial<PlanResponse> = {};

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
          if (activeAssistantId === messageId) return;
          activeAssistantId = messageId;
          setMessages((prev) => {
            const exists = prev.some((msg) => msg.id === messageId);
            if (exists) return prev;
            return [...prev, { id: messageId, role: 'assistant', content: '' }];
          });
        };

        const appendAssistantDelta = (
          messageId: string,
          delta: string,
          followUp?: string | null
        ) => {
          setMessages((prev) =>
            prev.map((msg) => {
              if (msg.id !== messageId) return msg;
              const next = `${msg.content || ''}${delta}`;
              const withFollowUp = followUp ? `${next}\n\n${followUp}` : next;
              return { ...msg, content: withFollowUp };
            })
          );
        };

        const applyCompleteSnapshot = (plan: PlanResponse) => {
          handlePlanResult(plan);
          if (plan.assistant_message_id && plan.assistant_message) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === plan.assistant_message_id
                  ? { ...msg, content: plan.assistant_message }
                  : msg
              )
            );
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

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
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
    <div className="bg-card/90 text-foreground flex h-full flex-col gap-3 rounded-2xl border border-white/20 p-4 shadow-xl backdrop-blur">
      <div className="flex items-center justify-between">
        <div className="text-muted-foreground text-[11px] font-semibold uppercase tracking-wide">
          Travel planner
        </div>
        {isLoading && (
          <Loader2 className="text-accent h-4 w-4 animate-spin" aria-label="Loading" />
        )}
      </div>

      <div ref={scrollContainerRef} className="flex-1 space-y-2 overflow-y-auto text-sm">
        {messages.map((m) => (
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

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          className="border-input bg-muted/60 text-foreground placeholder:text-muted-foreground focus-visible:ring-primary focus-visible:ring-offset-card flex-1 rounded-xl border px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2"
          placeholder="Describe your ideal trip..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isLoading}
        />
        <button
          type="submit"
          className="bg-primary text-primary-foreground hover:bg-primary/90 rounded-xl px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-60"
          disabled={isLoading}
        >
          {isLoading ? 'Thinking…' : 'Plan'}
        </button>
      </form>
    </div>
  );
}
