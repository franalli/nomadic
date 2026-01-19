// frontend/components/ChatPanel.tsx
'use client';

import * as Collapsible from '@radix-ui/react-collapsible';
import { ArrowUp, ChevronDown, Compass, RotateCcw, Sparkles, Square } from 'lucide-react';
import {
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { type SSENodeStatusEvent, streamGraphPlan, trackSuggestionClick } from '@/lib/api';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
import type { ChatMessage } from '@/types/chat';
import type {
  DocumentBranch,
  DocumentTripInputs,
  GraphPlanResponse,
} from '@/types/document';
import { INITIAL_PLAN_STATUS, type PlanStatus } from '@/types/plan-status';
import type { Tile } from '@/types/tile';

import { ChatSkeleton } from './ChatSkeleton';
import { HoldToDeleteButton } from './HoldToDeleteButton';
import { NodeProgress } from './NodeProgress';
import { SpecialistProgress } from './SpecialistProgress';

// Helper to fix escaped characters from backend
// Converts literal escape sequences to actual characters for proper markdown rendering
const sanitizeContent = (content: string): string => {
  return content
    .replace(/\\n/g, '\n')  // Replace literal \n with actual newlines
    .replace(/\\t/g, '\t')  // Replace literal \t with actual tabs
    .replace(/\\\*/g, '*'); // Unescape asterisks for markdown bold/italic
};
// ID prefix for "ready to generate" messages that should be replaced when branches are created
const READY_MESSAGE_ID_PREFIX = 'ready_';

// Prompt suggestions - insert starter text into input, not send messages
// These are conversation primers that disappear after first submit
const PROMPT_SUGGESTIONS = [
  { label: 'Destination', starterText: 'going to ' },
  { label: 'Origin', starterText: 'from ' },
  { label: 'Dates', starterText: 'dates are ' },
  { label: 'Budget', starterText: 'budget around ' },
] as const;

// Fallback suggestions when backend returns none but fields are missing
const FALLBACK_SUGGESTIONS: Record<string, string[]> = {
  start_date: ['Next weekend', 'March 15-22', '2 weeks from now', 'Flexible dates'],
  end_date: ['1 week trip', '10 days', '2 weeks'],
  budget: ['$1500 budget', '$3000 budget', '$5000 budget', 'Flexible budget'],
  origin: ['New York', 'London', 'San Francisco'],
  destinations: ['Tokyo', 'Paris', 'Barcelona', 'Bali'],
};

// Helper to generate specific error messages based on error type
function getErrorMessage(error: Error): string {
  const message = error.message?.toLowerCase() ?? '';

  // Network/connection errors
  if (message.includes('network') || message.includes('fetch') || message.includes('failed to fetch')) {
    return "Couldn't connect to the server. Please check your internet connection and try again.";
  }

  // Timeout errors
  if (message.includes('timeout') || message.includes('timed out')) {
    return "The request took too long. Try a simpler query or check your connection.";
  }

  // Rate limiting
  if (message.includes('rate limit') || message.includes('too many requests') || message.includes('429')) {
    return "You're sending requests too quickly. Please wait a moment before trying again.";
  }

  // Authentication errors
  if (message.includes('unauthorized') || message.includes('401') || message.includes('authentication')) {
    return "Session expired. Please refresh the page and try again.";
  }

  // Server errors
  if (message.includes('500') || message.includes('internal server') || message.includes('server error')) {
    return "Something went wrong on our end. Please try again in a few moments.";
  }

  // Validation errors (from backend)
  if (message.includes('invalid') || message.includes('validation')) {
    return "Invalid request. Try rephrasing or adjusting trip details.";
  }

  // Default fallback
  return "An issue occurred. Try again or adjust the message.";
}

// Tier 11.12: Check if an error message is retryable (transient network/server issues)
function isRetryableError(content: string): boolean {
  const retryablePatterns = [
    "couldn't connect",
    'check your internet',
    'took too long',
    'check your connection',
    'too quickly',
    'wait a moment',
    'went wrong on our end',
    'try again in a few',
  ];
  const lowerContent = content.toLowerCase();
  return retryablePatterns.some((pattern) => lowerContent.includes(pattern));
}

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
// Full GFM support with professional styling for chat bubbles
const MARKDOWN_COMPONENTS = {
  // Paragraphs with proper spacing
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>
  ),
  // Bold text with emphasis
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  // Italic text
  em: ({ children }: { children?: React.ReactNode }) => (
    <em className="italic">{children}</em>
  ),
  // Unordered lists with proper bullet styling
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="my-2 ml-1 list-none space-y-1.5 first:mt-0 last:mb-0">{children}</ul>
  ),
  // Ordered lists with proper number styling
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="my-2 ml-1 list-decimal space-y-1.5 pl-4 first:mt-0 last:mb-0">{children}</ol>
  ),
  // List items with custom bullet point styling (hidden when emoji acts as bullet)
  li: ({ children }: { children?: React.ReactNode }) => {
    // Extract text content to check if it starts with an emoji
    const getTextContent = (node: React.ReactNode): string => {
      if (typeof node === 'string') return node;
      if (Array.isArray(node)) return node.map(getTextContent).join('');
      if (node && typeof node === 'object' && 'props' in node) {
        const element = node as { props?: { children?: React.ReactNode } };
        return getTextContent(element.props?.children);
      }
      return '';
    };
    const text = getTextContent(children);
    const startsWithEmoji = /^[\p{Emoji_Presentation}\p{Extended_Pictographic}]/u.test(text);

    return (
      <li className={`relative pl-4 ${!startsWithEmoji ? "before:absolute before:left-0 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-primary/60 before:content-['']" : ''}`}>
        {children}
      </li>
    );
  },
  // Inline code for technical terms
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-muted/50 px-1 py-0.5 font-mono text-sm">{children}</code>
  ),
  // Links with proper styling
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline decoration-primary/50 underline-offset-2 hover:decoration-primary transition-colors"
    >
      {children}
    </a>
  ),
  // Blockquotes for emphasis or quotes
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-primary/40 pl-3 italic text-muted-foreground first:mt-0 last:mb-0">
      {children}
    </blockquote>
  ),
  // Horizontal rules for section breaks
  hr: () => <hr className="my-3 border-border/50" />,
  // Headers (rarely used in chat but supported)
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-2 text-lg font-bold first:mt-0">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-2 text-base font-semibold first:mt-0">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-1.5 text-sm font-semibold first:mt-0">{children}</h3>
  ),
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

    // Use chat store for messages, history loading, and session state
    const messages = useChatStore((state) => state.messages);
    const addMessage = useChatStore((state) => state.addMessage);
    const updateMessage = useChatStore((state) => state.updateMessage);
    const appendToMessage = useChatStore((state) => state.appendToMessage);
    const updateMessageId = useChatStore((state) => state.updateMessageId);
    const filterMessages = useChatStore((state) => state.filterMessages);
    const isLoadingHistory = useChatStore((state) => state.isLoadingHistory);
    const loadHistory = useChatStore((state) => state.loadHistory);
    const sessionState = useChatStore((state) => state.sessionState);
    const setSessionState = useChatStore((state) => state.setSessionState);
    const deleteLastMessageFromStore = useChatStore((state) => state.deleteLastMessage);

    // Document store for restoring trip inputs on delete
    const restoreTripInputs = useDocumentStore((state) => state.restoreTripInputs);
    // Get tripInputs for constraint state tracking
    const tripInputs = useDocumentStore((state) => state.document?.trip_inputs);

    const [input, setInput] = useState('');
    const [isDeleting, setIsDeleting] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
    const [hasReceivedFirstToken, setHasReceivedFirstToken] = useState(false);
    // Mobile detection for responsive collapsed defaults
    const [isMobile, setIsMobile] = useState(false);
    const [tripDetailsOpen, setTripDetailsOpen] = useState(true);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    // Initialize from localStorage to persist hint state across sessions
    const [hasShownHint, setHasShownHint] = useState(() => {
      if (typeof window === 'undefined') return false;
      return localStorage.getItem('nomadic-trip-details-hint-shown') === 'true';
    });
    const [readyMessageShown, setReadyMessageShown] = useState(false);
    const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
    // Tier 11.12: Track last user message for retry on transient errors
    const [lastUserMessage, setLastUserMessage] = useState<string | null>(null);
    // Node progress tracking for showing progress bar instead of typing dots
    const [nodeStatus, setNodeStatus] = useState<{
      active: boolean;
      node: string;
      label: string;
      iconKey: string;
      estimatedDurationMs: number;
      startTime: number;
      // Strategy-specific (optional)
      stage?: number;
      topic?: string;
    } | null>(null);
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const tripInputsRef = useRef<HTMLDivElement | null>(null);
    const panelRef = useRef<HTMLDivElement | null>(null);
    const prevIsLoadingRef = useRef(false);
    const bottomSentinelRef = useRef<HTMLDivElement | null>(null);
    const isUserScrolledUpRef = useRef(false);
    const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const abortStreamRef = useRef<(() => void) | null>(null);
    const hasUserMessage = messages.some((msg) => msg.role === 'user');
    const showTripDetails = Boolean(tripDetails) && hasUserMessage;
    // Show suggestions only when no user messages yet, not generating, not ready to generate, and not in planning mode (hasBranches)
    const showSuggestions = !hasUserMessage && !isLoadingHistory && !hasBranches && !isGenerating && !readyToGenerate;

    // Derive PlanStatus for SpecialistProgress
    // TODO: This should come from a central store/hook once specialist tracking is implemented
    const planStatus: PlanStatus = useMemo(() => ({
      ...INITIAL_PLAN_STATUS,
      phase: isGenerating ? 'updating' : (tripDetails?.missingFields?.length ? 'needs_input' : 'ready'),
      missing: tripDetails?.missingFields ?? [],
      dirty: false,
      activeSpecialists: [], // TODO: Track from SSE events
    }), [isGenerating, tripDetails?.missingFields]);

    // Compute effective suggestions: use backend suggestions if available, otherwise fallback based on missing fields
    const effectiveSuggestions = useMemo(() => {
      if (suggestedResponses.length > 0) return suggestedResponses;
      if (!hasUserMessage || isLoading || hasBranches) return [];
      const missingFields = tripDetails?.missingFields ?? [];
      if (missingFields.length === 0) return [];
      // Get fallback for first missing field
      const firstMissing = missingFields[0];
      return FALLBACK_SUGGESTIONS[firstMissing] ?? [];
    }, [suggestedResponses, hasUserMessage, isLoading, hasBranches, tripDetails?.missingFields]);

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

    // Stop streaming when user clicks the stop button
    const handleStopStreaming = useCallback(() => {
      if (abortStreamRef.current) {
        abortStreamRef.current();
        abortStreamRef.current = null;
      }

      // Mark message as interrupted with a user-friendly message
      if (streamingMessageId) {
        const currentMsg = messages.find((m) => m.id === streamingMessageId);
        const currentContent = (currentMsg?.content || '').trim();
        updateMessage(streamingMessageId, {
          content: currentContent + '\n\n*[Response stopped. You can continue the conversation or ask me to elaborate.]*',
        });
      }

      // Reset states
      setStreamingMessageId(null);
      setNodeStatus(null);
      setHasReceivedFirstToken(false);
      setIsLoading(false);
    }, [streamingMessageId, messages, updateMessage]);

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

    // Load chat history from store (only loads once, persists across remounts)
    useEffect(() => {
      loadHistory();
    }, [loadHistory]);

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
    // Persist hint state to localStorage so users don't see it repeatedly
    useEffect(() => {
      if (hasUserMessage && !hasShownHint) {
        // Mark hint as shown after animation duration and persist to localStorage
        const timer = setTimeout(() => {
          setHasShownHint(true);
          localStorage.setItem('nomadic-trip-details-hint-shown', 'true');
        }, 2000);
        return () => clearTimeout(timer);
      }
    }, [hasUserMessage, hasShownHint]);

    // Reset generate-related state when readyToGenerate becomes false
    // This ensures a clean slate after Fresh Start or when requirements are no longer met
    useEffect(() => {
      if (!readyToGenerate) {
        setReadyMessageShown(false);
        setGenerateTriggered(false);
        // Remove any "ready to generate" messages from the chat
        filterMessages((msg) => !msg.id.startsWith(READY_MESSAGE_ID_PREFIX));
      }
    }, [readyToGenerate, filterMessages]);

    // Note: Ready-to-generate message is now handled by the backend in summarize()
    // The backend sends: "Great news! I have everything I need to plan your trip..."
    // No need for a separate frontend message
    useEffect(() => {
      if (readyToGenerate && !readyMessageShown && !hasBranches && !generateTriggered) {
        setReadyMessageShown(true);
        // Backend now provides the ready message via streaming response
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
          content: isGenerateTrigger ? 'Generate plan' : trimmed,
        };
        addMessage(userMessage);
        setSuggestedResponses([]); // Clear suggestions when user sends a message
        setLastUserMessage(trimmed); // Tier 11.12: Track for retry capability
        setIsLoading(true);

        // Create a message bubble for streaming tokens into
        const streamingMsgId = `a_stream_${Date.now()}`;
        addMessage({ id: streamingMsgId, role: 'assistant', content: '' });
        setStreamingMessageId(streamingMsgId);
        setHasReceivedFirstToken(false); // Reset for new streaming message

        // Use SSE streaming for real-time token display
        const body = {
          message: trimmed,
          session_state: sessionState ?? undefined,
        };

        // Create a promise that resolves when streaming completes
        await new Promise<void>((resolve) => {
          abortStreamRef.current = streamGraphPlan(body, {
            onToken: (token: string) => {
              // Mark that we've received the first token (hides typing/progress indicator)
              setHasReceivedFirstToken(true);
              // Append token to the streaming message
              appendToMessage(streamingMsgId, token);
            },
            onNodeStatus: (status: SSENodeStatusEvent['data']) => {
              if (status.status === 'started') {
                setNodeStatus({
                  active: true,
                  node: status.node,
                  label: status.label,
                  iconKey: status.icon_key,
                  estimatedDurationMs: status.estimated_duration_ms,
                  startTime: Date.now(),
                  // Strategy-specific fields (optional)
                  stage: status.stage,
                  topic: status.topic,
                });
              }
            },
            onComplete: (response) => {
              setStreamingMessageId(null);
              setNodeStatus(null); // Clear strategy progress on completion
              abortStreamRef.current = null; // Clear abort ref

              // Parse the response - it matches GraphPlanResponse structure
              const data = response as unknown as GraphPlanResponse;

              // Persist session state for next turn
              setSessionState(data.session_state ?? null);

              // Handle plan result
              const doc = data.document;
              const primaryBranch =
                doc.branches?.find((b) => b.is_primary) ?? doc.branches?.[0];
              onPlanResult({
                tripContextId: doc.trip_context_id ?? null,
                branches: doc.branches ?? [],
                tiles: doc.tiles ?? {},
                primaryBranchId: primaryBranch?.id ?? selectedBranchId ?? null,
                tripInputs: doc.trip_inputs ?? null,
                readyToGenerate: doc.ready_to_generate ?? false,
                response: data,
              });

              const hasBranchesNow = (doc.branches?.length ?? 0) > 0;
              const isReadyToGenerate = doc.ready_to_generate === true;

              // Update suggested responses from LLM (if provided)
              setSuggestedResponses(doc.suggested_responses || []);

              if (hasBranchesNow) {
                // Branches generated: remove streaming message
                // Status is now shown via PlanHeaderStatus, not as a chat message
                filterMessages((msg) => msg.id !== streamingMsgId);
              } else if (isReadyToGenerate) {
                // Update the streaming message ID to use the ready prefix
                // so it can be removed when generation starts
                updateMessageId(streamingMsgId, `${READY_MESSAGE_ID_PREFIX}${streamingMsgId}`);
              }

              setIsLoading(false);
              resolve();
            },
            onError: (error: Error) => {
              setStreamingMessageId(null);
              setNodeStatus(null); // Clear strategy progress on error
              abortStreamRef.current = null; // Clear abort ref
              console.error('Failed to plan trip', error);

              // Replace streaming message with specific error message
              const errorMessage = getErrorMessage(error);
              const errorMsgId = `a_err_${Date.now()}`;
              updateMessageId(streamingMsgId, errorMsgId);
              updateMessage(errorMsgId, { content: errorMessage });

              setIsLoading(false);
              resolve(); // Resolve instead of reject to prevent unhandled promise rejection
            },
          });
        });
      },
      [isLoading, onPlanResult, onGeneratePlanStart, selectedBranchId, sessionState, addMessage, appendToMessage, filterMessages, updateMessageId, updateMessage, setSessionState]
    );

    const addAssistantMessage = useCallback((message: string) => {
      const assistantMessage: ChatMessage = {
        id: `a_ui_${Date.now()}`,
        role: 'assistant',
        content: message,
      };
      addMessage(assistantMessage);
      // Scroll panel into view and focus input after message is added (matches LLM response behavior)
      scrollPanelIntoView();
      requestAnimationFrame(() => {
        inputRef.current?.focus();
      });
    }, [scrollPanelIntoView, addMessage]);

    // Handle deleting the last user message (undo)
    const handleDeleteLastMessage = useCallback(async () => {
      if (isDeleting || isLoading) return;

      setIsDeleting(true);
      try {
        const result = await deleteLastMessageFromStore();
        if (result.success && result.restoredTripInputs) {
          // Restore trip inputs in document store
          restoreTripInputs(result.restoredTripInputs as DocumentTripInputs);
        }
      } catch (error) {
        console.error('Failed to delete message:', error);
      } finally {
        setIsDeleting(false);
      }
    }, [isDeleting, isLoading, deleteLastMessageFromStore, restoreTripInputs]);

    // Find the last user message ID for showing delete button
    const lastUserMessageId = messages
      .filter((m) => m.role === 'user')
      .at(-1)?.id ?? null;

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
    // During generation, hide the initial welcome message to keep focus on the "All details collected" message
    // After branches are ready, replace the welcome message with a prompt to refine the trip
    // Split assistant messages by paragraph breaks into separate bubbles for better readability
    const visibleMessages = messages
      .filter((m) => {
        if (!m.content || m.content.trim().length === 0) return false;
        if (isGenerating && m.id === 'm0') return false;
        return true;
      })
      .map((m) => {
        if (hasBranches && m.id === 'm0') {
          return { ...m, content: 'Edit constraints.' };
        }
        return m;
      })
      // Sanitize content: convert literal \n to actual newlines
      .map((m) => ({
        ...m,
        content: sanitizeContent(m.content),
      }))
      .flatMap((m) => {
        // Only split assistant messages by paragraph breaks
        if (m.role === 'assistant') {
          const paragraphs = m.content.split(/\n\n+/).filter((p) => p.trim().length > 0);
          if (paragraphs.length > 1) {
            return paragraphs.map((paragraph, idx) => ({
              ...m,
              id: `${m.id}_p${idx}`,
              content: paragraph.trim(),
              // Mark as part of a split message for styling consistency
              _isPartOfSplit: true,
              _isFirstPart: idx === 0,
              _isLastPart: idx === paragraphs.length - 1,
            }));
          }
        }
        return m;
      });

    // Show typing indicator when loading and haven't received first streaming token yet
    // Don't show when node progress is active (we show progress bar instead)
    const showTypingIndicator = isLoading && !hasReceivedFirstToken && !nodeStatus?.active;
    // Show node progress when an LLM node is executing, hide once tokens start arriving
    const showNodeProgress = isLoading && !hasReceivedFirstToken && nodeStatus?.active;

    return (
      <div
        ref={panelRef}
        className={`text-foreground flex ${panelHeightClass} min-h-0 w-full flex-col gap-4 transition-[min-height,max-height] duration-300 bg-white dark:bg-[hsl(154,28%,8%)] dark:bg-[linear-gradient(to_bottom,hsl(154,28%,10%),hsl(154,28%,6%))] border border-gray-200/80 dark:border-transparent rounded-xl p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]`}
      >
        <div className="flex items-center justify-between border-b border-border/40 pb-3">
          <div className="text-foreground/80 text-xs font-semibold uppercase tracking-wider flex items-center gap-2">
            <Compass className="h-3.5 w-3.5 text-primary" />
            Travel Planner
          </div>
          <div className="flex items-center gap-3">
            {/* Reset button - always visible when onFreshStart is provided */}
            {onFreshStart && (
              <button
                type="button"
                onClick={() => {
                  if (window.confirm('Reset session? This will clear all trip details and history.')) {
                    onFreshStart?.();
                  }
                }}
                className="text-muted-foreground hover:text-foreground text-xs flex items-center gap-1 transition-colors"
                title="Reset session"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Reset</span>
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
            /* Tier 9: Skeleton loading for better perceived performance */
            <ChatSkeleton count={2} />
          ) : (
            <>
              {visibleMessages.map((m, idx) => {
                // Check if this is part of a split message (for styling and retry button logic)
                const isSplitMessage = '_isPartOfSplit' in m && m._isPartOfSplit;
                const isFirstPart = '_isFirstPart' in m && m._isFirstPart;
                const isLastPart = '_isLastPart' in m && m._isLastPart;
                // Extract original message ID for streaming check (handles split messages)
                const originalId = m.id.replace(/_p\d+$/, '');
                const isStreaming = streamingMessageId === originalId && !isSplitMessage;
                // Tighter spacing for consecutive parts of split messages
                const spacingClass = isSplitMessage && !isFirstPart ? '-mt-1.5' : '';

                // For user messages, wrap in a relative container for delete button positioning
                const isUserMessage = m.role === 'user';
                const showDeleteButton = isUserMessage && originalId === lastUserMessageId && !isLoading;

                return (
                  <div
                    key={m.id}
                    className={`${isUserMessage ? 'text-right' : 'text-left'} message-enter ${spacingClass}`}
                    style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
                  >
                    {/* Relative container for absolute delete button positioning */}
                    <div className={`inline-block relative max-w-[85%] ${showDeleteButton ? 'group/msg' : ''}`}>
                      <div
                        className={
                          isUserMessage
                            ? 'border border-primary/40 dark:border-accent/40 bg-gradient-to-br from-primary via-primary to-primary/70 text-primary-foreground dark:from-amber-500 dark:via-accent dark:to-amber-600/70 dark:text-white rounded-2xl rounded-br-md px-4 py-2.5 text-left transition-all shadow-[0_2px_6px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.2)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.2),0_4px_12px_rgba(0,0,0,0.15),inset_0_1px_0_rgba(255,255,255,0.15)] hover:shadow-[0_4px_10px_rgba(0,0,0,0.08),0_6px_16px_rgba(0,0,0,0.06),inset_0_1px_0_rgba(255,255,255,0.25)] dark:hover:shadow-[0_4px_10px_rgba(0,0,0,0.25),0_6px_16px_rgba(0,0,0,0.2),inset_0_1px_0_rgba(255,255,255,0.2)] hover:-translate-y-0.5 hover:border-primary/60 dark:hover:border-accent/60'
                            : `border border-border/40 bg-gradient-to-br from-muted via-muted to-muted/70 text-foreground rounded-2xl rounded-bl-md px-4 py-2.5 transition-all shadow-[0_2px_6px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.04),inset_0_1px_0_rgba(255,255,255,0.6)] dark:shadow-[0_2px_6px_rgba(0,0,0,0.2),0_4px_12px_rgba(0,0,0,0.15),inset_0_1px_0_rgba(255,255,255,0.08)] hover:shadow-[0_4px_10px_rgba(0,0,0,0.08),0_6px_16px_rgba(0,0,0,0.06),inset_0_1px_0_rgba(255,255,255,0.6)] dark:hover:shadow-[0_4px_10px_rgba(0,0,0,0.25),0_6px_16px_rgba(0,0,0,0.2),inset_0_1px_0_rgba(255,255,255,0.1)] hover:-translate-y-0.5 hover:border-border/60 ${isStreaming ? 'typing-pulse' : ''}`
                        }
                      >
                        {m.role === 'assistant' ? (
                          <>
                            <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                              {m.content}
                            </Markdown>
                            {/* Tier 11.12: Retry button for transient errors - only on last part of split messages */}
                            {originalId.startsWith('a_err_') &&
                              lastUserMessage &&
                              isRetryableError(m.content) &&
                              !isLoading &&
                              (!isSplitMessage || isLastPart) && (
                                <button
                                  type="button"
                                  onClick={() => sendMessageCore(lastUserMessage)}
                                  className="mt-2 flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 transition-colors"
                                >
                                  <RotateCcw className="h-3 w-3" />
                                  Retry
                                </button>
                              )}
                          </>
                        ) : (
                          <>{m.content}</>
                        )}
                      </div>
                      {/* Delete button - positioned at bottom-right corner, visible only on hover */}
                      {showDeleteButton && (
                        <div className="absolute -bottom-4 right-1 opacity-0 group-hover/msg:opacity-100 transition-opacity z-[999]">
                          <HoldToDeleteButton
                            onDelete={handleDeleteLastMessage}
                            disabled={isDeleting}
                          />
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              {showTypingIndicator && <TypingIndicator />}
              {showNodeProgress && nodeStatus && (
                <NodeProgress
                  node={nodeStatus.node}
                  label={nodeStatus.label}
                  iconKey={nodeStatus.iconKey}
                  estimatedDurationMs={nodeStatus.estimatedDurationMs}
                  startTime={nodeStatus.startTime}
                  stage={nodeStatus.stage}
                  topic={nodeStatus.topic}
                />
              )}
              {/* Invisible sentinel for smooth scroll-to-bottom */}
              <div ref={bottomSentinelRef} aria-hidden="true" className="h-px" />
            </>
          )}
        </div>

        {/* Input area with suggestions - grouped together at bottom */}
        <div className="mt-auto space-y-2 pb-0">
          {/* Constraint chips - conversation primers that insert starter text */}
          {showSuggestions && (
            <div className="flex flex-wrap justify-center gap-2 py-1">
              {PROMPT_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion.label}
                  type="button"
                  onClick={() => {
                    // Append starter text - chips accumulate, separated by comma
                    const separator = input.trim() ? ', ' : '';
                    setInput(prev => prev + separator + suggestion.starterText);
                    inputRef.current?.focus();
                  }}
                  className="text-xs px-3.5 py-2 rounded-lg border border-dashed border-muted-foreground/25 text-muted-foreground/70 hover:border-muted-foreground/40 hover:text-muted-foreground transition-colors"
                >
                  <span className="font-medium">{suggestion.label}</span>
                </button>
              ))}
            </div>
          )}

          {/* Dynamic suggestions - from backend or fallback based on missing fields */}
          {effectiveSuggestions.length > 0 && !isLoading && !showSuggestions && (
            <div
              key={`suggestions-container-${effectiveSuggestions.length}`}
              className="flex flex-wrap justify-center gap-1.5 pt-3 pb-1 px-2"
            >
              {effectiveSuggestions.map((suggestion, idx) => (
                <button
                  key={`sugg-${suggestion.slice(0, 20)}-${idx}`}
                  type="button"
                  onClick={() => {
                    // Track suggestion click for analytics (fire-and-forget)
                    trackSuggestionClick(suggestion, idx);
                    sendMessageCore(suggestion);
                  }}
                  className="text-xs px-3 py-1.5 rounded-full bg-gradient-to-b from-card to-muted/40 border border-border/60 hover:border-primary/40 text-foreground/70 hover:text-primary shadow-pill-accent hover:shadow-pill-hover transition-all duration-200 max-w-full truncate"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          {/* Specialist progress - system strip above input (subordinate to header status) */}
          <SpecialistProgress status={planStatus} />

          <form onSubmit={handleSubmit} className="relative">
            {/* Static placeholder - only when input is empty and no user message */}
            {!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory && (
              <div className="absolute top-0 left-0 right-0 px-4 py-3 text-sm text-muted-foreground/70 pointer-events-none" aria-hidden="true">
                {hasBranches ? 'Edit constraints' : 'Enter destination'}
              </div>
            )}
            <textarea
            ref={inputRef}
            className={`border-input bg-muted/40 hover:bg-muted/60 text-foreground focus-visible:ring-primary focus-visible:ring-offset-card w-full rounded-xl border-2 px-4 py-3 pr-14 text-sm focus:outline-none focus:bg-muted/50 focus-visible:ring-2 focus-visible:ring-offset-1 transition-colors resize-none overflow-y-auto no-scrollbar min-h-[48px] max-h-[200px] scroll-mb-4 ${!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory ? 'placeholder:text-transparent' : 'placeholder:text-muted-foreground/70'}`}
            placeholder={
              hasBranches
                ? 'Edit constraints…'
                : 'Enter destination'
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
          {isLoading && hasReceivedFirstToken ? (
            // Stop streaming button - orange square
            <button
              type="button"
              onClick={handleStopStreaming}
              className="absolute right-2 top-[6px] flex items-center justify-center rounded-lg p-2 text-sm font-semibold transition-all bg-orange-500 text-white hover:bg-orange-600 hover:scale-105 shadow-md"
              title="Stop streaming"
            >
              <Square className="h-5 w-5 fill-current" />
            </button>
          ) : (
            // Send button
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
              <ArrowUp className="h-5 w-5" />
            </button>
          )}
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
                className="group w-full flex items-center justify-center gap-2 py-2 px-4 text-sm font-semibold text-primary border border-primary/30 rounded-full bg-primary/5 hover:bg-primary/10 hover:border-primary/50 transition-all disabled:opacity-50 dark:text-accent dark:border-accent/40 dark:bg-accent/10 dark:hover:bg-accent/20 dark:hover:border-accent/60"
              >
                <Sparkles className="h-4 w-4 transition-transform group-hover:scale-110" />
                <span>Generate Plan</span>
              </button>
            </div>
          </div>
        </div>

        {/* Trip inputs section - positioned below chat input */}
        {showTripDetails && (
          <div ref={tripInputsRef} className="mt-1.5 pt-1.5 pb-3 border-t border-border/50 space-y-4">
            <Collapsible.Root open={tripDetailsOpen} onOpenChange={(open) => {
              setTripDetailsOpen(open);
              // Mark hint as shown when user manually opens trip details
              if (open && !hasShownHint) {
                setHasShownHint(true);
                localStorage.setItem('nomadic-trip-details-hint-shown', 'true');
              }
            }}>
              <div>
                <Collapsible.Trigger asChild>
                  <button className="w-full flex items-center gap-2 text-primary text-[11px] font-bold uppercase leading-none tracking-wider mb-0 py-1.5 px-2 -mx-2 rounded-lg transition-all duration-200 hover:bg-primary/5 group">
                    <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-200 ${tripDetailsOpen ? '' : '-rotate-90'}`} />
                    Constraints
                    {/* Show hint text on collapsed state for mobile users who haven't seen it yet */}
                    {!tripDetailsOpen && !hasShownHint && (
                      <span className="ml-auto text-[10px] text-muted-foreground font-normal normal-case tracking-normal">
                        Tap to customize preferences
                      </span>
                    )}
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
