// frontend/components/ChatPanel.tsx
'use client';

import { useMemo, useState } from 'react';

import type { PlanRequest, PlanResponse } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type { PlanBranch } from '@/types/plan';
import type { Tile } from '@/types/tile';
import { getOrCreateSessionId } from '@/lib/session';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface ChatPanelProps {
  onBranchesChange: (branches: PlanBranch[]) => void;
  onTilesChange: (tiles: Tile[]) => void;
  onPrimaryBranchSelected: (branchId: string | null) => void;
  onTilesRequestIdChange?: (requestId: string | null) => void;
  onTripContextChange: (tripContextId: number | null) => void;
  origin: string;
  startDate: string;
  endDate: string;
  budgetBucket: string;
  groupSize: string;
  vibes: string[];
  onOriginChange: (value: string) => void;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onBudgetBucketChange: (value: string) => void;
  onGroupSizeChange: (value: string) => void;
  onVibesChange: (values: string[]) => void;
  onClearContext: () => void;
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

  const vibeOptions = useMemo(
    () => [
      { value: 'foodie', label: 'Foodie' },
      { value: 'nightlife', label: 'Nightlife' },
      { value: 'culture', label: 'Culture' },
      { value: 'outdoors', label: 'Outdoors' },
      { value: 'relaxation', label: 'Relaxation' },
      { value: 'family', label: 'Family' },
    ],
    []
  );

  function toggleVibe(value: string) {
    const nextVibes = props.vibes.includes(value)
      ? props.vibes.filter((v) => v !== value)
      : [...props.vibes, value];
    props.onVibesChange(nextVibes);
  }

  function clearContext() {
    props.onClearContext();
  }

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
        group_size: props.groupSize ? Number(props.groupSize) : undefined,
        vibes: props.vibes,
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

      // Update tiles + branches in parent
      props.onBranchesChange(data.branches);
      props.onTilesChange(data.tiles);
      props.onPrimaryBranchSelected(data.branches[0]?.id ?? null);
      props.onTilesRequestIdChange?.(data.tiles_request_id ?? null);
      props.onTripContextChange(data.trip_context_id ?? null);

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
      <section className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <div className="flex items-center justify-between text-slate-700">
          <p className="text-sm font-semibold">Trip context</p>
          <button
            type="button"
            className="text-xs font-medium text-blue-600 hover:underline"
            onClick={clearContext}
          >
            Clear
          </button>
        </div>

        <div className="grid gap-3 text-xs md:grid-cols-2">
          <label className="space-y-1">
            <span className="font-medium uppercase tracking-wide text-slate-500">
              Origin
            </span>
            <input
              className="w-full rounded-md border border-slate-200 px-2 py-1"
              placeholder="e.g. Amsterdam"
              value={props.origin}
              onChange={(e) => props.onOriginChange(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="font-medium uppercase tracking-wide text-slate-500">
              Budget
            </span>
            <select
              className="w-full rounded-md border border-slate-200 px-2 py-1"
              value={props.budgetBucket}
              onChange={(e) => props.onBudgetBucketChange(e.target.value)}
            >
              <option value="">Flexible</option>
              <option value="value">Value</option>
              <option value="mid">Mid</option>
              <option value="premium">Premium</option>
              <option value="luxury">Luxury</option>
            </select>
          </label>

          <label className="space-y-1">
            <span className="font-medium uppercase tracking-wide text-slate-500">
              Start
            </span>
            <input
              type="date"
              className="w-full rounded-md border border-slate-200 px-2 py-1"
              value={props.startDate}
              onChange={(e) => props.onStartDateChange(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="font-medium uppercase tracking-wide text-slate-500">
              End
            </span>
            <input
              type="date"
              className="w-full rounded-md border border-slate-200 px-2 py-1"
              value={props.endDate}
              onChange={(e) => props.onEndDateChange(e.target.value)}
            />
          </label>

          <label className="space-y-1">
            <span className="font-medium uppercase tracking-wide text-slate-500">
              Group size
            </span>
            <input
              type="number"
              min="1"
              className="w-full rounded-md border border-slate-200 px-2 py-1"
              value={props.groupSize}
              onChange={(e) => props.onGroupSizeChange(e.target.value)}
            />
          </label>
        </div>

        <div className="space-y-2">
          <p className="font-medium uppercase tracking-wide text-slate-500">Vibes</p>
          <div className="flex flex-wrap gap-2">
            {vibeOptions.map((option) => {
              const isActive = props.vibes.includes(option.value);
              const baseClasses =
                'rounded-full border px-3 py-1 text-[11px] font-medium transition-colors';
              return (
                <button
                  key={option.value}
                  type="button"
                  className={
                    isActive
                      ? `${baseClasses} border-blue-500 bg-blue-50 text-blue-600`
                      : `${baseClasses} border-slate-200 bg-white text-slate-600`
                  }
                  onClick={() => toggleVibe(option.value)}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>
      </section>

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
