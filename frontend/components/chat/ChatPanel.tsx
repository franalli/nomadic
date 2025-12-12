// frontend/components/ChatPanel.tsx
'use client';

import * as Collapsible from '@radix-ui/react-collapsible';
import { ArrowUp, ChevronDown, Compass, RotateCcw, Sparkles } from 'lucide-react';
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
import type { GraphPlanRequest } from '@/types/api';
import type { ChatMessage } from '@/types/chat';
import type {
  DocumentBranch,
  DocumentTripInputs,
  GraphPlanResponse,
} from '@/types/document';
import type { Tile } from '@/types/tile';

const STREAM_CHUNK_SIZE = 1; // characters per chunk for smooth typing
const STREAM_DELAY_MS = 35; // delay between chunks in ms (~29 chars/sec)
// Special message that triggers plan generation (must match backend _GENERATE_PLAN_TRIGGER)
const GENERATE_PLAN_TRIGGER = 'GENERATE_PLAN_NOW';
// Message to show after plan is generated with specific examples
const POST_GENERATE_MESSAGE =
  "Your trip options are ready! You can say things like 'increase budget to $3000', 'remove Paris', or 'add a beach day' to refine your plan.";
// ID prefix for "ready to generate" messages that should be replaced when branches are created
const READY_MESSAGE_ID_PREFIX = 'ready_';

// Prompt suggestions for new users - quick start options
const PROMPT_SUGGESTIONS = [
  { label: '🏖️ Beach getaway', prompt: "I want a relaxing beach vacation" },
  { label: '🏔️ Adventure trip', prompt: "Plan an adventure trip with hiking and outdoor activities" },
  { label: '🏛️ City break', prompt: "I'd like to explore a vibrant city with culture and nightlife" },
  { label: '👨‍👩‍👧 Family trip', prompt: "Plan a family-friendly vacation with activities for kids" },
];

const DEFAULT_MESSAGES: ChatMessage[] = [
  {
    id: 'm0',
    role: 'assistant',
    content:
      "Hey there! ✈️ I'm excited to help you plan an amazing trip! Where are you dreaming of going?",
  },
];

// Typing indicator component - extracted to module level to prevent recreation
const TypingIndicator = () => (
  <div className="text-left message-enter">
    <div className="border border-border/40 bg-gradient-to-br from-muted via-muted to-muted/70 text-foreground inline-flex items-center gap-1.5 rounded-2xl rounded-bl-md px-4 py-3 shadow-[0_2px_6px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.6)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.2),0_4px_12px_rgba(0,0,0,0.15),inset_0_1px_0_rgba(255,255,255,0.08)]">
      <span className="typing-dot h-2 w-2 rounded-full bg-primary/60" style={{ animationDelay: '0ms' }} />
      <span className="typing-dot h-2 w-2 rounded-full bg-primary/60" style={{ animationDelay: '150ms' }} />
      <span className="typing-dot h-2 w-2 rounded-full bg-primary/60" style={{ animationDelay: '300ms' }} />
    </div>
  </div>
);

// Markdown components config - extracted to module level to prevent recreation on each render
const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }: { children?: React.ReactNode }) => <strong className="font-semibold">{children}</strong>,
  ul: ({ children }: { children?: React.ReactNode }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
  ol: ({ children }: { children?: React.ReactNode }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
  li: ({ children }: { children?: React.ReactNode }) => <li className="mb-1">{children}</li>,
};

interface ChatPanelProps {
  selectedBranchId: string | null;
  /** Called when generate plan trigger is sent (before API call) */
  onGeneratePlanStart?: () => void;
  /** Called when user clicks Fresh Start to reset the session */
  onFreshStart?: () => void;
  onPlanResult: (result: {
    tripContextId: number | null;
    branches: DocumentBranch[];
    tiles: Record<string, Tile>;
    primaryBranchId: string | null;
    tripInputs?: DocumentTripInputs | null;
    readyToGenerate?: boolean;
    // Full response for store update
    response?: GraphPlanResponse;
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
  /** When true, plan generation is in progress */
  isGenerating?: boolean;
}

export interface ChatPanelHandle {
  sendMessage: (message: string) => Promise<void>;
  addAssistantMessage: (message: string) => void;
}

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(
  function ChatPanel(props, ref) {
    // Destructure all props for consistent access pattern
    const {
      onPlanResult,
      onGeneratePlanStart,
      selectedBranchId,
      tripDetails,
      fullHeight,
      hasBranches,
      isGenerating,
      readyToGenerate,
      onFreshStart,
    } = props;

    const [messages, setMessages] = useState<ChatMessage[]>(DEFAULT_MESSAGES);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [isLoadingHistory, setIsLoadingHistory] = useState(true);
    const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
    // Mobile detection for responsive collapsed defaults
    const [isMobile, setIsMobile] = useState(false);
    const [tripDetailsOpen, setTripDetailsOpen] = useState(true);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    const [hasShownHint, setHasShownHint] = useState(false);
    const [readyMessageShown, setReadyMessageShown] = useState(false);
    const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
    const [sessionState, setSessionState] = useState<Record<string, unknown> | null>(null);
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const tripInputsRef = useRef<HTMLDivElement | null>(null);
    const panelRef = useRef<HTMLDivElement | null>(null);
    const prevIsLoadingRef = useRef(false);
    const bottomSentinelRef = useRef<HTMLDivElement | null>(null);
    const isUserScrolledUpRef = useRef(false);
    const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const hasUserMessage = messages.some((msg) => msg.role === 'user');
    const showTripDetails = Boolean(tripDetails) && hasUserMessage;
    // Show suggestions only when no user messages yet
    const showSuggestions = !hasUserMessage && !isLoadingHistory;
    // Dynamic height - grows with content naturally
    const panelHeightClass = fullHeight
      ? 'h-full'
      : 'min-h-[300px]';

    // Check if user is near the bottom of the scroll container
    const isNearBottom = useCallback(() => {
      const node = scrollContainerRef.current;
      if (!node) return true;
      const threshold = 100; // pixels from bottom to consider "at bottom"
      return node.scrollHeight - node.scrollTop - node.clientHeight < threshold;
    }, []);

    // Custom smooth scroll with controlled duration
    const smoothScrollTo = useCallback((element: HTMLElement, targetScrollTop: number, duration: number) => {
      const startScrollTop = element.scrollTop;
      const distance = targetScrollTop - startScrollTop;
      const startTime = performance.now();

      // Ease-out cubic for natural deceleration
      const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

      const animateScroll = (currentTime: number) => {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easedProgress = easeOutCubic(progress);

        element.scrollTop = startScrollTop + distance * easedProgress;

        if (progress < 1) {
          requestAnimationFrame(animateScroll);
        }
      };

      requestAnimationFrame(animateScroll);
    }, []);

    // Smooth scroll to bottom using custom animation
    const scrollToBottom = useCallback((force = false) => {
      // Don't auto-scroll if user has scrolled up, unless forced
      if (!force && isUserScrolledUpRef.current) return;

      const container = scrollContainerRef.current;
      if (!container) return;

      // Debounce rapid scroll calls to prevent jitter
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }

      scrollTimeoutRef.current = setTimeout(() => {
        const targetScrollTop = container.scrollHeight - container.clientHeight;
        // 2000ms duration for a slow, relaxed scroll
        smoothScrollTo(container, targetScrollTop, 2000);
      }, 16); // Single frame delay for batching
    }, [smoothScrollTo]);

    // Track user scroll position to avoid fighting user scroll
    const handleScroll = useCallback(() => {
      isUserScrolledUpRef.current = !isNearBottom();
    }, [isNearBottom]);

    // Scroll the page to bring chat panel into view (used after send/receive)
    const scrollPanelIntoView = useCallback(() => {
      requestAnimationFrame(() => {
        panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
      });
    }, []);

    // Scroll panel into view and focus input when response finishes (isLoading: true -> false)
    useEffect(() => {
      if (prevIsLoadingRef.current && !isLoading) {
        // Reset scroll tracking and force scroll to bottom when response finishes
        isUserScrolledUpRef.current = false;
        scrollToBottom(true);
        scrollPanelIntoView();
        requestAnimationFrame(() => {
          inputRef.current?.focus();
        });
      }
      prevIsLoadingRef.current = isLoading;
    }, [isLoading, scrollToBottom, scrollPanelIntoView]);

    // Cleanup timeout on unmount
    useEffect(() => {
      return () => {
        if (scrollTimeoutRef.current) {
          clearTimeout(scrollTimeoutRef.current);
        }
      };
    }, []);

    // Scroll to bottom when messages change (during streaming or new messages)
    useEffect(() => {
      // Only auto-scroll if there are messages and we're not in loading history state
      if (messages.length > 0 && !isLoadingHistory) {
        scrollToBottom();
      }
    }, [messages, isLoadingHistory, scrollToBottom]);

    // Reset scroll tracking when user sends a message (starts loading)
    useEffect(() => {
      if (isLoading) {
        isUserScrolledUpRef.current = false;
      }
    }, [isLoading]);

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
                  // Transform any stored trigger to friendly text (handles legacy data)
                  content: m.content === GENERATE_PLAN_TRIGGER ? 'Generate my trip options' : m.content,
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

    // Detect mobile viewport and set responsive collapsed defaults
    useEffect(() => {
      const checkMobile = () => {
        const mobile = window.innerWidth < 640; // sm breakpoint
        setIsMobile(mobile);
      };
      checkMobile();
      window.addEventListener('resize', checkMobile);
      return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // Set collapsed defaults on mobile when trip inputs first appear
    useEffect(() => {
      if (hasUserMessage && isMobile && !hasShownHint) {
        setTripDetailsOpen(false);
      }
    }, [hasUserMessage, isMobile, hasShownHint]);

    // Track when hint animation should show (first time trip details appear)
    useEffect(() => {
      if (hasUserMessage && !hasShownHint) {
        // Mark hint as shown after animation duration
        const timer = setTimeout(() => setHasShownHint(true), 2000);
        return () => clearTimeout(timer);
      }
    }, [hasUserMessage, hasShownHint]);

    // Show ready to generate message when all details are collected
    useEffect(() => {
      if (readyToGenerate && !readyMessageShown && !hasBranches && !generateTriggered) {
        setReadyMessageShown(true);
        setMessages((prev) => [
          ...prev,
          {
            id: `${READY_MESSAGE_ID_PREFIX}${Date.now()}`,
            role: 'assistant' as const,
            content: "✨ All details collected — ready to generate your trip options!",
          },
        ]);
      }
    }, [readyToGenerate, readyMessageShown, hasBranches, generateTriggered]);

    const sendMessageCore = useCallback(
      async (messageText: string) => {
        const trimmed = messageText.trim();
        if (!trimmed || isLoading) return;

        const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER;

        // Notify parent that generate plan has started (for loading screen)
        if (isGenerateTrigger) {
          onGeneratePlanStart?.();
        }

        // Add user message - show friendly text for generate trigger
        const userMessage: ChatMessage = {
          id: `u_${Date.now()}`,
          role: 'user',
          content: isGenerateTrigger ? 'Generate my trip options' : trimmed,
        };
        setMessages((prev) => [...prev, userMessage]);
        setSuggestedResponses([]); // Clear suggestions when user sends a message
        setIsLoading(true);

        try {
          const body: GraphPlanRequest = {
            message: trimmed,
            session_state: sessionState ?? undefined,
          };

          const res = await apiFetch('/v1/graph_plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });

          if (!res.ok) {
            const text = await res.text();
            throw new Error(text || `Plan failed: ${res.status}`);
          }

          const data: GraphPlanResponse = await res.json();

          // Persist session state for next turn
          setSessionState(data.session_state ?? null);

          const handlePlanResultInternal = (payload: GraphPlanResponse) => {
            const doc = payload.document;
            const primaryBranch =
              doc.branches.find((b) => b.is_primary) ?? doc.branches[0];
            onPlanResult({
              tripContextId: doc.trip_context_id ?? null,
              branches: doc.branches,
              tiles: doc.tiles,
              primaryBranchId: primaryBranch?.id ?? selectedBranchId ?? null,
              tripInputs: doc.trip_inputs ?? null,
              readyToGenerate: doc.ready_to_generate ?? false,
              // Pass full response for store update
              response: payload,
            });
          };

          handlePlanResultInternal(data);

          const hasBranchesNow = data.document.branches.length > 0;
          const isReadyToGenerate = data.document.ready_to_generate === true;

          // Update suggested responses from LLM (if provided)
          setSuggestedResponses(data.document.suggested_responses || []);

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
          // Note: Backend always provides assistant_message, fallback is just for safety
          const assistantText =
            data.document.assistant_message || "Here are your trip options!";
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
      [isLoading, onPlanResult, onGeneratePlanStart, selectedBranchId, sessionState]
    );

    const addAssistantMessage = useCallback((message: string) => {
      const assistantMessage: ChatMessage = {
        id: `a_ui_${Date.now()}`,
        role: 'assistant',
        content: message,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      // Scroll panel into view and focus input after message is added (matches LLM response behavior)
      scrollPanelIntoView();
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }, [scrollPanelIntoView]);

    // Handle clicking a prompt suggestion
    const handleSuggestionClick = useCallback((prompt: string) => {
      setInput(prompt);
      inputRef.current?.focus();
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        sendMessage: sendMessageCore,
        addAssistantMessage,
      }),
      [sendMessageCore, addAssistantMessage]
    );

    async function handleSubmit(e: React.FormEvent) {
      e.preventDefault();
      const trimmed = input.trim();
      if (!trimmed || isLoading) return;
      setInput('');
      // Reset textarea height after clearing
      if (inputRef.current) {
        inputRef.current.style.height = 'auto';
      }
      setTimeout(() => inputRef.current?.focus(), 0);
      await sendMessageCore(trimmed);
    }

    // Simple render - no content-based filters, just show all non-empty messages
    const visibleMessages = messages.filter((m) => m.content && m.content.trim().length > 0);

    // Show typing indicator when loading and no streaming message yet
    const showTypingIndicator = isLoading && !streamingMessageId;

    return (
      <div
        ref={panelRef}
        className={`text-foreground flex ${panelHeightClass} min-h-0 w-full flex-col gap-4 transition-[min-height,max-height] duration-300 bg-white dark:bg-bg-strong/60 border border-gray-200/80 dark:border-transparent rounded-xl p-4`}
      >
        <div className="flex items-center justify-between border-b border-border/40 pb-3">
          <div className="text-foreground/80 text-xs font-semibold uppercase tracking-wider flex items-center gap-2">
            <Compass className="h-3.5 w-3.5 text-primary" />
            Travel Planner
          </div>
          <div className="flex items-center gap-3">
            {/* Fresh Start button */}
            {onFreshStart && hasUserMessage && (
              <button
                type="button"
                onClick={() => {
                  if (window.confirm('Start fresh? This will clear all your trip details and chat history.')) {
                    onFreshStart?.();
                  }
                }}
                className="text-muted-foreground hover:text-foreground text-xs flex items-center gap-1 transition-colors"
                title="Start fresh"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Fresh Start</span>
              </button>
            )}
          </div>
        </div>

        <div
          ref={scrollContainerRef}
          className="min-h-0 flex-1 space-y-3 overflow-y-auto text-sm no-scrollbar"
          style={{ overflowAnchor: 'none' }}
          role="log"
          aria-label="Chat messages"
          aria-busy={isLoadingHistory || isLoading}
          onScroll={handleScroll}
        >
          {isLoadingHistory ? (
            <div className="flex items-center justify-center py-4" role="status" aria-label="Loading chat history">
              <Compass className="text-muted-foreground compass-spin h-5 w-5" aria-hidden="true" />
              <span className="sr-only">Loading chat history...</span>
            </div>
          ) : (
            <>
              {visibleMessages.map((m, idx) => (
                <div
                  key={m.id}
                  className={`${m.role === 'user' ? 'text-right' : 'text-left'} message-enter`}
                  style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
                >
                  <div
                    className={
                      m.role === 'user'
                        ? 'bg-gradient-to-br from-primary via-primary to-primary/85 text-primary-foreground inline-block max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-left transition-all shadow-[0_2px_8px_rgba(0,0,0,0.12),0_4px_16px_rgba(0,0,0,0.08),inset_0_1px_0_rgba(255,255,255,0.2)] hover:shadow-[0_4px_12px_rgba(0,0,0,0.15),0_8px_24px_rgba(0,0,0,0.1),inset_0_1px_0_rgba(255,255,255,0.25)] hover:-translate-y-0.5'
                        : `border border-border/40 bg-gradient-to-br from-muted via-muted to-muted/70 text-foreground inline-block max-w-[85%] rounded-2xl rounded-bl-md px-4 py-2.5 transition-all shadow-[0_2px_6px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.6)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.2),0_4px_12px_rgba(0,0,0,0.15),inset_0_1px_0_rgba(255,255,255,0.08)] hover:shadow-[0_4px_10px_rgba(0,0,0,0.08),0_6px_16px_rgba(0,0,0,0.06),inset_0_1px_0_rgba(255,255,255,0.6)] dark:hover:shadow-[0_4px_10px_rgba(0,0,0,0.25),0_6px_16px_rgba(0,0,0,0.2),inset_0_1px_0_rgba(255,255,255,0.1)] hover:-translate-y-0.5 hover:border-border/60 ${streamingMessageId === m.id ? 'typing-pulse' : ''}`
                    }
                  >
                    {m.role === 'assistant' ? (
                      <Markdown components={MARKDOWN_COMPONENTS}>
                        {m.content}
                      </Markdown>
                    ) : (
                      m.content
                    )}
                  </div>
                </div>
              ))}
              {showTypingIndicator && <TypingIndicator />}
              {/* Invisible sentinel for smooth scroll-to-bottom */}
              <div ref={bottomSentinelRef} aria-hidden="true" className="h-px" />
            </>
          )}
        </div>

        {/* Input area with suggestions - grouped together at bottom */}
        <div className="mt-auto space-y-2 pb-0">
          {/* Prompt suggestions for new users - quick start options */}
          {showSuggestions && (
            <div className="flex flex-wrap justify-center gap-2 py-1">
              {PROMPT_SUGGESTIONS.map((suggestion, idx) => (
                <button
                  key={suggestion.label}
                  type="button"
                  onClick={() => handleSuggestionClick(suggestion.prompt)}
                  className="group text-xs px-3.5 py-2 rounded-lg bg-muted/30 hover:bg-primary/10 border border-transparent hover:border-primary/20 text-foreground/70 hover:text-primary transition-all duration-200 hover:shadow-sm hover:-translate-y-0.5"
                  style={{ animationDelay: `${idx * 75}ms` }}
                >
                  <span className="inline-block transition-transform duration-200 group-hover:scale-110 mr-1.5">{suggestion.label.split(' ')[0]}</span>
                  <span className="font-medium">{suggestion.label.split(' ').slice(1).join(' ')}</span>
                </button>
              ))}
            </div>
          )}

          {/* Dynamic LLM-generated suggestions */}
          {suggestedResponses.length > 0 && !isLoading && !showSuggestions && (
            <div className="flex flex-wrap justify-center gap-1.5 pt-3 pb-1 px-2">
              {suggestedResponses.map((suggestion, idx) => (
                <button
                  key={`sugg-${idx}`}
                  type="button"
                  onClick={() => {
                    sendMessageCore(suggestion);
                  }}
                  className="suggestion-enter text-xs px-3 py-1.5 rounded-full bg-gradient-to-b from-card to-muted/40 border border-border/60 hover:border-primary/40 text-foreground/70 hover:text-primary shadow-pill-accent hover:shadow-pill-hover transition-all duration-200 max-w-full truncate"
                  style={{ animationDelay: `${idx * 500}ms` }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit} className="relative">
            {/* Custom shimmer placeholder - only when input is empty and no user message */}
            {!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory && (
              <div className="placeholder-shimmer" aria-hidden="true">
                {hasBranches ? 'Refine your trip...' : 'Where would you like to go?'}
              </div>
            )}
            <textarea
            ref={inputRef}
            className={`border-input bg-muted/40 hover:bg-muted/60 text-foreground focus-visible:ring-primary focus-visible:ring-offset-card w-full rounded-xl border-2 px-4 py-3 pr-14 text-sm focus:outline-none focus:bg-muted/50 focus-visible:ring-2 focus-visible:ring-offset-1 transition-colors resize-none overflow-y-auto no-scrollbar min-h-[48px] max-h-[200px] scroll-mb-4 ${!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory ? 'placeholder:text-transparent' : 'placeholder:text-muted-foreground/70'}`}
            placeholder={
              hasBranches
                ? 'Refine your trip...'
                : 'Where would you like to go?'
            }
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              // Auto-resize textarea
              e.target.style.height = 'auto';
              e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(e) => {
              // Submit on Enter without Shift
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
            rows={1}
          />
          <button
            type="submit"
            className={`absolute right-2 top-[6px] flex items-center justify-center rounded-lg p-2 text-sm font-semibold transition-all disabled:opacity-50 ${
              input.trim() && !isLoading
                ? 'bg-primary text-primary-foreground hover:bg-primary/90 hover:scale-105 shadow-md'
                : 'bg-muted/80 text-muted-foreground hover:bg-muted'
            }`}
            disabled={isLoading || !input.trim()}
            title="Send message (Enter)"
          >
            <ArrowUp className={`h-5 w-5 ${!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory ? 'send-arrow-shimmer' : ''}`} />
          </button>
          </form>

          {/* Generate button - directly under input */}
          <div
            className={`grid transition-all duration-300 ease-out ${
              !hasBranches && !generateTriggered && !isGenerating && readyToGenerate
                ? 'grid-rows-[1fr] opacity-100'
                : 'grid-rows-[0fr] opacity-0 pointer-events-none'
            }`}
          >
            <div className="overflow-hidden">
              <button
                type="button"
                onClick={() => {
                  setGenerateTriggered(true);
                  sendMessageCore(GENERATE_PLAN_TRIGGER);
                }}
                disabled={isLoading || !readyToGenerate}
                className="group w-full flex items-center justify-center gap-2 py-2 px-4 text-sm font-semibold text-primary border border-primary/30 rounded-full bg-primary/5 hover:bg-primary/10 hover:border-primary/50 transition-all disabled:opacity-50 generate-shimmer dark:text-accent dark:border-accent/40 dark:bg-accent/10 dark:hover:bg-accent/20 dark:hover:border-accent/60 dark:shadow-[0_0_20px_hsl(25_85%_55%/0.25)] dark:hover:shadow-[0_0_30px_hsl(25_85%_55%/0.4)]"
              >
                <Sparkles className="h-4 w-4 transition-transform group-hover:scale-110" />
                <span>Generate Trip Options</span>
              </button>
            </div>
          </div>
        </div>

        {/* Trip inputs section - positioned below chat input */}
        {showTripDetails && (
          <div ref={tripInputsRef} className="mt-1.5 pt-1.5 pb-3 border-t border-border/50 space-y-4">
            <Collapsible.Root open={tripDetailsOpen} onOpenChange={setTripDetailsOpen}>
              <div>
                <Collapsible.Trigger asChild>
                  <button className={`w-full flex items-center gap-2 text-primary text-[11px] font-bold uppercase leading-none tracking-wider mb-0 py-1.5 px-2 -mx-2 rounded-lg transition-all duration-200 hover:bg-primary/5 group ${!hasShownHint ? 'animate-pulse' : ''}`}>
                    <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-200 ${tripDetailsOpen ? '' : '-rotate-90'}`} />
                    Trip Details
                  </button>
                </Collapsible.Trigger>
                <Collapsible.Content className="overflow-hidden data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up">
                  <div className="text-sm pt-3">{tripDetails?.content}</div>
                </Collapsible.Content>
              </div>
            </Collapsible.Root>
          </div>
        )}

      </div>
    );
  }
);
