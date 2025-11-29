// frontend/components/ChatPanel.tsx
'use client';

import { ArrowUp, ChevronDown, Compass } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react';

import { API_BASE } from '@/lib/api';
import { getOrCreateSessionId } from '@/lib/session';
import type { PlanRequest } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type {
  DocumentBranch,
  DocumentTripInputs,
  PlanDocumentResponse,
} from '@/types/document';
import type { Tile } from '@/types/tile';

const CHAT_HISTORY_KEY = 'chat_history';
const STREAM_CHUNK_SIZE = 6;
const STREAM_DELAY_MS = 25;
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
  selectedBranchId: string | null;
  onChatTriggered?: () => void;
  onHasUserMessage?: (has: boolean) => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: DocumentBranch[];
    tiles: Record<string, Tile>;
    primaryBranchId: string | null;
    tripInputs?: DocumentTripInputs | null;
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

const summariseBranches = (branches: DocumentBranch[]): string => {
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
      // Get or create session ID
      const activeSessionId = sessionId ?? getOrCreateSessionId();
      if (!sessionId) {
        setSessionId(activeSessionId);
      }

      // All state flows through the document - request only needs session + message
      const body: PlanRequest = {
        session_id: activeSessionId,
        message: trimmed,
      };

      const res = await fetch(`${API_BASE}/v1/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Plan failed: ${res.status}`);
      }

      const data: PlanDocumentResponse = await res.json();

      const handlePlanResult = (payload: PlanDocumentResponse) => {
        const doc = payload.document;
        const primaryBranch = doc.branches.find((b) => b.is_primary) ?? doc.branches[0];
        props.onPlanResult({
          tripContextId: doc.trip_context_id ?? null,
          branches: doc.branches,
          tiles: doc.tiles,
          primaryBranchId: primaryBranch?.id ?? props.selectedBranchId ?? null,
          tripInputs: doc.trip_inputs ?? null,
        });
      };

      handlePlanResult(data);

      const assistantText =
        data.document.assistant_message || summariseBranches(data.document.branches);
      const msgId = data.document.assistant_message_id ?? `a_${Date.now()}`;

      const sentences = assistantText
        .split(/(?<=[.!?])\s+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0);

      const streamTextIntoMessage = (messageId: string, text: string) =>
        new Promise<void>((resolve) => {
          if (!text.length) {
            resolve();
            return;
          }
          let idx = 0;
          const interval = setInterval(() => {
            const nextChunk = text.slice(idx, idx + STREAM_CHUNK_SIZE);
            idx += STREAM_CHUNK_SIZE;
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === messageId
                  ? { ...msg, content: `${msg.content || ''}${nextChunk}` }
                  : msg
              )
            );
            if (idx >= text.length) {
              clearInterval(interval);
              resolve();
            }
          }, STREAM_DELAY_MS);
        });

      const streamAssistantSentences = async () => {
        if (!sentences.length) return;
        // Remove any existing bubbles for this message ID
        setMessages((prev) => prev.filter((msg) => !msg.id.startsWith(`${msgId}_s`)));

        for (let i = 0; i < sentences.length; i += 1) {
          const bubbleId = `${msgId}_s${i}`;
          const text = sentences[i];
          setMessages((prev) => [
            ...prev,
            { id: bubbleId, role: 'assistant', content: '' },
          ]);
          // eslint-disable-next-line no-await-in-loop
          await streamTextIntoMessage(bubbleId, text);
        }
      };

      await streamAssistantSentences();
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
          className={`absolute right-1 top-1/2 flex -translate-y-1/2 items-center justify-center rounded-lg px-3 py-1 text-sm font-semibold transition-colors disabled:opacity-60 ${
            isLoading
              ? 'bg-transparent'
              : 'bg-primary text-primary-foreground hover:bg-primary/90'
          }`}
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
