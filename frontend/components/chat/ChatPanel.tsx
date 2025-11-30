// frontend/components/ChatPanel.tsx
'use client';

import { ArrowUp, ChevronDown, Compass } from 'lucide-react';
import {
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import Markdown from 'react-markdown';

import { apiFetch } from '@/lib/api';
import type { PlanRequest } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type {
  DocumentBranch,
  DocumentTripInputs,
  PlanDocumentResponse,
} from '@/types/document';
import type { Tile } from '@/types/tile';

const STREAM_CHUNK_SIZE = 1; // characters per chunk for smooth typing
const STREAM_DELAY_MS = 24; // delay between chunks in ms (~55 chars/sec, natural typing speed)
// Special message that triggers plan generation (must match backend _GENERATE_PLAN_TRIGGER)
const GENERATE_PLAN_TRIGGER = 'GENERATE_PLAN_NOW';
// Message to show after plan is generated
const POST_GENERATE_MESSAGE = 'Keep chatting to tweak and improve your plan!';
// ID prefix for "ready to generate" messages that should be replaced when branches are created
const READY_MESSAGE_ID_PREFIX = 'ready_';

const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    id: 'm0',
    role: 'assistant',
    content:
      "Hey there! ✈️ I'm excited to help you plan an amazing trip! Where are you dreaming of going?",
  },
];

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
    readyToGenerate?: boolean;
    // Full response for store update
    response?: PlanDocumentResponse;
  }) => void;
  tripDetails?: {
    content: ReactNode;
    missingFields?: string[];
  };
  /** When true, the panel will try to fill available height */
  fullHeight?: boolean;
  /** When true, branches have been generated */
  hasBranches?: boolean;
  /** When true, all fields are complete and user can generate a plan */
  readyToGenerate?: boolean;
}

const summariseBranches = (branches: DocumentBranch[]): string => {
  if (!branches.length) {
    return 'I could not settle on clear directions yet, but here are some starter booking options.';
  }

  const lines = branches.map((branch, idx) => {
    const destLabel = branch.destinations.join(', ') || 'TBD';
    const label = `${idx + 1}. ${branch.label} (${destLabel})`;
    return branch.description ? `${label}\n   ${branch.description}` : label;
  });

  return ['Here are a few trip directions I would consider:', ...lines].join('\n\n');
};

export interface ChatPanelHandle {
  sendMessage: (message: string) => Promise<void>;
}

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(
  function ChatPanel(props, ref) {
    const { onHasUserMessage } = props;
    const [messages, setMessages] = useState<ChatMessage[]>(DEFAULT_MESSAGES);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isLoadingHistory, setIsLoadingHistory] = useState(true);
    const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
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

    // Load chat history from backend API on mount
    useEffect(() => {
      const loadChatHistory = async () => {
        try {
          const res = await apiFetch('/v1/chat');
          if (res.ok) {
            const data = await res.json();
            if (data.messages && data.messages.length > 0) {
              const loadedMessages: ChatMessage[] = data.messages.map(
                (m: { id: string; role: string; content: string }) => ({
                  id: m.id,
                  role: m.role as 'user' | 'assistant',
                  content: m.content,
                })
              );
              setMessages(loadedMessages);
            }
          }
        } catch (error) {
          console.error('Failed to load chat history', error);
          // Keep default messages on error
        } finally {
          setIsLoadingHistory(false);
        }
      };
      loadChatHistory();
    }, []);

    useEffect(() => {
      inputRef.current?.focus();
    }, []);

    const sendMessageCore = useCallback(
      async (messageText: string) => {
        const trimmed = messageText.trim();
        if (!trimmed || isLoading) return;

        props.onChatTriggered?.();

        const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER;

        if (!isGenerateTrigger) {
          const userMessage: ChatMessage = {
            id: `u_${Date.now()}`,
            role: 'user',
            content: trimmed,
          };
          setMessages((prev) => [...prev, userMessage]);
        }
        setIsLoading(true);

        try {
          const body: PlanRequest = {
            message: trimmed,
          };

          const res = await apiFetch('/v1/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });

          if (!res.ok) {
            const text = await res.text();
            throw new Error(text || `Plan failed: ${res.status}`);
          }

          const data: PlanDocumentResponse = await res.json();

          const handlePlanResultInternal = (payload: PlanDocumentResponse) => {
            const doc = payload.document;
            const primaryBranch =
              doc.branches.find((b) => b.is_primary) ?? doc.branches[0];
            props.onPlanResult({
              tripContextId: doc.trip_context_id ?? null,
              branches: doc.branches,
              tiles: doc.tiles,
              primaryBranchId: primaryBranch?.id ?? props.selectedBranchId ?? null,
              tripInputs: doc.trip_inputs ?? null,
              readyToGenerate: doc.ready_to_generate ?? false,
              // Pass full response for store update
              response: payload,
            });
          };

          handlePlanResultInternal(data);

          const hasBranchesNow = data.document.branches.length > 0;
          const isReadyToGenerate = data.document.ready_to_generate === true;

          if (hasBranchesNow) {
            // Branches generated: remove "ready" messages (by ID prefix) and add post-generate message
            setMessages((prev) => {
              const filtered = prev.filter((msg) => !msg.id.startsWith(READY_MESSAGE_ID_PREFIX));
              const newMessages = [
                ...filtered,
                { id: `post_${Date.now()}`, role: 'assistant' as const, content: POST_GENERATE_MESSAGE },
              ];
              return newMessages;
            });
            return;
          }

          // Stream the assistant's response
          const assistantText =
            data.document.assistant_message || summariseBranches(data.document.branches);
          const msgId = data.document.assistant_message_id ?? `a_${Date.now()}`;

          // If this is a "ready to generate" response, use a special ID prefix so we can remove it later
          const baseId = isReadyToGenerate ? READY_MESSAGE_ID_PREFIX + msgId : msgId;

          // Split into bubbles: by newlines first (preserves list items), then by sentences
          const splitIntoBubbles = (text: string): string[] => {
            const bubbles: string[] = [];
            // Split by double newlines (paragraphs) or single newlines (list items)
            const blocks = text.split(/\n+/).map((b) => b.trim()).filter((b) => b.length > 0);

            for (const block of blocks) {
              // If it's a list item (starts with number. or - or *), keep it as one bubble
              if (/^(\d+\.|[-*])/.test(block)) {
                bubbles.push(block);
              } else {
                // Otherwise split by sentence-ending punctuation
                const sentences = block
                  .split(/(?<=[.!?])\s+/)
                  .map((s) => s.trim())
                  .filter((s) => s.length > 0);
                bubbles.push(...sentences);
              }
            }
            return bubbles;
          };

          const bubbleTexts = splitIntoBubbles(assistantText);

          const streamTextIntoMessage = (messageId: string, text: string) =>
            new Promise<void>((resolve) => {
              if (!text.length) {
                resolve();
                return;
              }
              setStreamingMessageId(messageId);
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
                  setStreamingMessageId(null);
                  resolve();
                }
              }, STREAM_DELAY_MS);
            });

          const streamAssistantBubbles = async () => {
            if (!bubbleTexts.length) return;
            setMessages((prev) => prev.filter((msg) => !msg.id.startsWith(`${baseId}_s`)));

            for (let i = 0; i < bubbleTexts.length; i += 1) {
              const bubbleId = `${baseId}_s${i}`;
              const text = bubbleTexts[i];
              setMessages((prev) => [
                ...prev,
                { id: bubbleId, role: 'assistant', content: '' },
              ]);
              await streamTextIntoMessage(bubbleId, text);
            }
          };

          await streamAssistantBubbles();
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
      },
      [isLoading, props]
    );

    useImperativeHandle(
      ref,
      () => ({
        sendMessage: sendMessageCore,
      }),
      [sendMessageCore]
    );

    async function handleSubmit(e: React.FormEvent) {
      e.preventDefault();
      const trimmed = input.trim();
      if (!trimmed || isLoading) return;
      setInput('');
      setTimeout(() => inputRef.current?.focus(), 0);
      await sendMessageCore(trimmed);
    }

    // Simple render - no content-based filters, just show all non-empty messages
    const visibleMessages = messages.filter((m) => m.content && m.content.trim().length > 0);

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
          {isLoadingHistory ? (
            <div className="flex items-center justify-center py-4">
              <Compass className="text-muted-foreground compass-spin h-5 w-5" />
            </div>
          ) : (
            visibleMessages.map((m) => (
              <div key={m.id} className={m.role === 'user' ? 'text-right' : 'text-left'}>
                <div
                  className={
                    m.role === 'user'
                      ? 'bg-primary text-primary-foreground inline-block max-w-[80%] rounded-2xl px-3 py-2 shadow-sm text-left'
                      : `border-border/60 bg-muted text-foreground inline-block max-w-[80%] rounded-2xl border px-3 py-2 transition-opacity ${streamingMessageId === m.id ? 'typing-pulse' : ''}`
                  }
                >
                  {m.role === 'assistant' ? (
                    <Markdown
                      components={{
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                        ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
                        ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
                        li: ({ children }) => <li className="mb-1">{children}</li>,
                      }}
                    >
                      {m.content}
                    </Markdown>
                  ) : (
                    m.content
                  )}
                </div>
              </div>
            ))
          )}
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

        <div
          className={`grid transition-all duration-300 ease-out ${
            props.readyToGenerate && !props.hasBranches
              ? 'grid-rows-[1fr] opacity-100'
              : 'grid-rows-[0fr] opacity-0'
          }`}
        >
          <div className="overflow-hidden">
            <button
              type="button"
              onClick={() => sendMessageCore(GENERATE_PLAN_TRIGGER)}
              disabled={isLoading || !props.readyToGenerate}
              className="bg-primary text-primary-foreground hover:bg-primary/90 mt-2 w-full rounded-xl px-4 py-3 text-sm font-semibold shadow-lg transition-colors disabled:opacity-60"
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <Compass className="compass-spin h-4 w-4" />
                  Generating...
                </span>
              ) : (
                'Generate Plan'
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }
);
