// frontend/components/ChatPanel.tsx
'use client';

import { useState } from 'react';

import { getOrCreateSessionId } from '@/lib/session';
import type { PlanRequest, PlanResponse } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface ChatPanelProps {
  origin: string;
  startDate: string;
  endDate: string;
  budgetBucket?: string;
  groupSize?: number;
  vibes: string[];
  tripContextId: number | null;
  selectedBranchId: string | null;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: PlanBranch[];
    tiles: Tile[];
    primaryBranchId: string | null;
    tilesRequestId: string | null;
  }) => void;
}

export function ChatPanel(props: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'm0',
      role: 'assistant',
      content: 'Tell me about your trip and I’ll suggest a few destinations.',
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

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
        user_id: undefined, // optional, wire later
        session_id: sessionId,
        message: trimmed,
        origin: props.origin || undefined,
        start_date: props.startDate || undefined,
        end_date: props.endDate || undefined,
        budget_bucket: props.budgetBucket || undefined,
        group_size: props.groupSize ?? undefined,
        vibes: props.vibes,
        trip_context_id: props.tripContextId ?? undefined,
      };

      const res = await fetch(`${API_BASE}/v1/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        throw new Error(`Plan failed: ${res.status}`);
      }

      const data: PlanResponse = await res.json();

      props.onPlanResult({
        tripContextId: data.trip_context_id ?? null,
        branches: data.branches,
        tiles: data.tiles,
        primaryBranchId: data.primary_branch_id ?? data.branches[0]?.id ?? null,
        tilesRequestId: data.tiles_request_id ?? null,
      });

      // Build assistant message summarising the branches
      const summaryLines =
        data.branches.length === 0
          ? ['I couldn’t find clear branches yet, but here are some initial tiles.']
          : data.branches.map((b, idx) => {
              const prefix = `${idx + 1}. ${b.label} (${b.destination})`;
              if (b.description) return `${prefix}\n   ${b.description}`;
              return prefix;
            });

      const assistantMessage: ChatMessage = {
        id: `a_${Date.now()}`,
        role: 'assistant',
        content:
          'Here are some trip directions I’d consider:\n\n' + summaryLines.join('\n\n'),
      };

      setMessages((prev) => [...prev, assistantMessage]);
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
    <div className="flex h-full flex-col gap-3 rounded-xl border p-3">
      <div className="flex-1 space-y-2 overflow-y-auto text-sm">
        {messages.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <div
              className={
                m.role === 'user'
                  ? 'inline-block rounded-xl bg-gray-200 px-3 py-2'
                  : 'inline-block rounded-xl bg-gray-100 px-3 py-2'
              }
            >
              {m.content}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          className="flex-1 rounded-lg border px-3 py-2 text-sm"
          placeholder="Describe your ideal trip..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isLoading}
        />
        <button
          type="submit"
          className="rounded-lg border px-4 py-2 text-sm"
          disabled={isLoading}
        >
          {isLoading ? 'Thinking...' : 'Plan'}
        </button>
      </form>
    </div>
  );
}
