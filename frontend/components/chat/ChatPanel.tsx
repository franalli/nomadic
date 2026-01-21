// frontend/components/ChatPanel.tsx
'use client';

import { ArrowUp, Lock, RotateCcw, Sparkles, Square } from 'lucide-react';
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { shouldShowLeftPanelGenerateCTA } from '@/components/plan/planStateHelpers';
import { OnboardingChips } from '@/components/planner/OnboardingChips';
import { OptionalRefinementsSection } from '@/components/planner/OptionalRefinementsSection';
import { useActionLoader } from '@/hooks/useActionLoader';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { type SSENodeStatusEvent, streamGraphPlan, trackSuggestionClick } from '@/lib/api';
import { classifyNodeAction, shouldShowLoaderForNode } from '@/lib/loaderConfig';
import type { TriggerContext } from '@/types/loader';
import { cn } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import type { LLMUpdatableField } from '@/state/documentStore';
import { useDocumentStore } from '@/state/documentStore';
import type { ChatMessage } from '@/types/chat';
import type {
  ActivitySettings,
  BookingTypes,
  DocumentBranch,
  DocumentTripInputs,
  FlightSettings,
  GraphPlanResponse,  HotelSettings,
  TransportSettings} from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { ChatSkeleton } from './ChatSkeleton';
import { CollapsedMessageRow } from './CollapsedMessageRow';
import { HoldToDeleteButton } from './HoldToDeleteButton';
import { NodeProgress } from './NodeProgress';

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
// Note: Budget removed - OnboardingChips already provides budget entry point
const PROMPT_SUGGESTIONS = [
  { label: 'Destination', starterText: 'going to ' },
  { label: 'Origin', starterText: 'from ' },
  { label: 'Dates', starterText: 'dates are ' },
] as const;

// Fallback suggestions when backend returns none but fields are missing
const FALLBACK_SUGGESTIONS: Record<string, string[]> = {
  start_date: ['Next weekend', 'In March', '2 weeks from now'],
  end_date: ['1 week trip', '10 days', '2 weeks'],
  budget: ['$2,000', '$5,000', '$10,000'],
  origin: ['New York', 'London', 'Dubai'],
  destinations: ['Tokyo', 'Paris', 'Bali'],
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
  /** When true, the panel will try to fill available height */
  fullHeight?: boolean;
  /** When true, branches have been generated */
  hasBranches?: boolean;
  /** When true, all fields are complete and user can generate a plan */
  readyToGenerate?: boolean;
  /** When true, plan generation is in progress */
  isGenerating?: boolean;
  /** Backend-authoritative plan state for left pane sync */
  planState?: 'INCOMPLETE' | 'RESOLVING' | 'STABLE' | 'LOCKED';
  // Onboarding chips props (state inspectors above input)
  /** Current destination for chip display */
  destination?: string;
  /** Current origin for chip display */
  origin?: string;
  /** Formatted date range string for chip display */
  dateRange?: string;
  /** Budget description for chip display */
  budget?: string;
  /** Whether user has chosen flexible dates */
  dateFlex?: boolean;
  /** Trip duration in days (for flexible dates display) */
  tripDuration?: number;
  // CTA gating flags
  /** Whether user has set a destination */
  hasDestination?: boolean;
  /** Whether user can generate a plan (has destination + dates) */
  canGeneratePlan?: boolean;
  /** Whether a plan has been generated (branches exist) */
  hasPlan?: boolean;
  // Optional Refinements Section props
  /** Whether user has set dates (for refinements gating) */
  hasDates?: boolean;
  /** Trip inputs for refinements */
  tripInputs?: DocumentTripInputs;
  /** Booking type settings */
  bookingTypes?: BookingTypes;
  /** Flight settings */
  flightSettings?: FlightSettings;
  /** Hotel settings */
  hotelSettings?: HotelSettings;
  /** Activity settings */
  activitySettings?: ActivitySettings;
  /** Transport settings */
  transportSettings?: TransportSettings;
  /** Update booking types callback */
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  /** Update flight settings callback */
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  /** Update hotel settings callback */
  onUpdateHotelSettings?: (settings: Partial<HotelSettings>) => void;
  /** Update transport settings callback */
  onUpdateTransportSettings?: (settings: Partial<TransportSettings>) => void;
  /** Add activity callback */
  onAddActivity?: (activity: string) => void;
  /** Remove activity callback */
  onRemoveActivity?: (index: number) => void;
  /** Update adults callback */
  onUpdateAdults?: (value: number | null) => void;
  /** Update children callback */
  onUpdateChildren?: (value: number | null) => void;
  /** Toggle requires assistance callback */
  onToggleRequiresAssistance?: () => void;
  /** LLM updated fields for visual indicators */
  llmUpdatedFields?: Set<LLMUpdatableField>;
  /** Acknowledge LLM update callback */
  onAcknowledgeLLMUpdate?: (field: LLMUpdatableField) => void;
  /** Plan view state for CTA gating (hide generate after S2) */
  planViewState?: PlanViewState;
  /** Open budget input in TripDetailsForm */
  onOpenBudgetInput?: () => void;
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
      fullHeight,
      hasBranches,
      isGenerating,
      readyToGenerate,
      onFreshStart: _onFreshStart, // Unused after Reset button moved to global header
      planState,
      // Onboarding chips props - click handlers are internal
      destination,
      origin,
      dateRange,
      budget,
      dateFlex,
      tripDuration,
      // CTA gating flags
      hasDestination = false,
      canGeneratePlan = false,
      hasPlan = false,
      // Optional Refinements Section props
      hasDates = false,
      tripInputs,
      bookingTypes,
      flightSettings,
      hotelSettings,
      activitySettings,
      transportSettings,
      onUpdateBookingTypes,
      onUpdateFlightSettings,
      onUpdateHotelSettings,
      onUpdateTransportSettings,
      onAddActivity,
      onRemoveActivity,
      onUpdateAdults,
      onUpdateChildren,
      onToggleRequiresAssistance,
      llmUpdatedFields,
      onAcknowledgeLLMUpdate,
      planViewState,
      onOpenBudgetInput,
    } = props;

    void _onFreshStart; // Reserved for future use - Reset button moved to global header

    // Derive input disabled state from planState (RESOLVING = disabled)
    const isInputDisabledByPlanState = planState === 'RESOLVING';

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

    const [input, setInput] = useState('');
    const [isDeleting, setIsDeleting] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
    const [hasReceivedFirstToken, setHasReceivedFirstToken] = useState(false);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    const [hasAnimatedPulse, setHasAnimatedPulse] = useState(false);
    const [readyMessageShown, setReadyMessageShown] = useState(false);
    const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
    // Track which messages are collapsed (by message ID)
    const [collapsedMessages, setCollapsedMessages] = useState<Set<string>>(new Set());
    // Track last user message ID for ack updates
    const lastUserMsgIdRef = useRef<string | null>(null);
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

    // Delayed loader: shows after 400ms delay, only for operations with ETA > 600ms
    // Avoids flicker for quick operations and only shows when user would wonder "is anything happening?"
    const delayedLoader = useDelayedLoader({ showDelay: 400, etaThreshold: 600 });

    // Action loader: extends delayedLoader with action-specific copy and classification
    // Only shows for 5 action types: generate_plan, update_plan, refresh_deals, create_itinerary, vertical_fetch
    const actionLoader = useActionLoader({ showDelay: 400, minEtaThreshold: 600 });

    // Track trigger context for action classification
    const [triggerContext, setTriggerContext] = useState<TriggerContext | null>(null);

    const scrollContainerRef = useRef<HTMLDivElement | null>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const panelRef = useRef<HTMLDivElement | null>(null);
    const prevIsLoadingRef = useRef(false);
    const bottomSentinelRef = useRef<HTMLDivElement | null>(null);
    const isUserScrolledUpRef = useRef(false);
    const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const abortStreamRef = useRef<(() => void) | null>(null);
    const hasUserMessage = messages.some((msg) => msg.role === 'user');

    // Generate plan button state machine
    type GenerateState = 'DISABLED_INCOMPLETE' | 'ENABLED_READY' | 'GENERATING' | 'GENERATED';
    const generateState: GenerateState = useMemo(() => {
      if (!canGeneratePlan) return 'DISABLED_INCOMPLETE';
      if (isLoading || generateTriggered) return 'GENERATING';
      if (hasPlan) return 'GENERATED';
      return 'ENABLED_READY';
    }, [canGeneratePlan, isLoading, generateTriggered, hasPlan]);

    // Track first transition to ENABLED_READY for pulse animation
    useEffect(() => {
      if (generateState === 'ENABLED_READY' && !hasAnimatedPulse) {
        setHasAnimatedPulse(true);
      }
    }, [generateState, hasAnimatedPulse]);

    // Compute effective suggestions: use backend suggestions if available, otherwise fallback based on missing fields
    // Note: missingFields now derived from planState instead of tripDetails
    const missingFields: string[] = [];
    const effectiveSuggestions = useMemo(() => {
      let suggestions: string[];
      if (suggestedResponses.length > 0) {
        suggestions = suggestedResponses;
      } else if (isLoading || hasBranches) {
        return [];
      } else if (missingFields.length === 0) {
        return [];
      } else {
        // Get fallback for first missing field
        const firstMissing = missingFields[0];
        suggestions = FALLBACK_SUGGESTIONS[firstMissing] ?? [];
      }

      // Dedupe: keep first occurrence of each field-type CTA (e.g., "Set budget")
      // to avoid multiple identical buttons
      const seen = new Set<string>();
      return suggestions.filter((s) => {
        const isFieldCTA = /^(set|add|change)\s/i.test(s);
        if (!isFieldCTA) return true;
        const lower = s.toLowerCase();
        if (seen.has(lower)) return false;
        seen.add(lower);
        return true;
      });
    }, [suggestedResponses, isLoading, hasBranches, missingFields]);

    // Show suggestions when: plan is incomplete, has missing fields, not generating, and has suggestions to show
    // This gates on state + missing fields, not ui_phase
    const showSuggestions =
      planState === 'INCOMPLETE' &&
      missingFields.length > 0 &&
      effectiveSuggestions.length > 0 &&
      !isLoadingHistory &&
      !isGenerating;

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
      delayedLoader.reset(); // Clear delayed loader on interrupt
    }, [streamingMessageId, messages, updateMessage, delayedLoader]);

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
      async (messageText: string, options?: { suggestionClicked?: string }) => {
        const trimmed = messageText.trim();
        if (!trimmed || isLoading) return;

        const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER;

        // Set trigger context for action classification
        // This helps classify the node_status events that follow
        setTriggerContext({
          isGeneratePlanTrigger: isGenerateTrigger,
          // If we already have branches and this isn't a generate trigger, it's a constraint change
          isConstraintChange: hasBranches && !isGenerateTrigger,
        });

        // Notify parent that generate plan has started (for loading screen)
        if (isGenerateTrigger) {
          onGeneratePlanStart?.();
        }

        // Add user message - show friendly text for generate trigger
        const userMsgId = `u_${Date.now()}`;
        const userMessage: ChatMessage = {
          id: userMsgId,
          role: 'user',
          content: isGenerateTrigger ? 'Generate plan' : trimmed,
          // Mark as constraint if not a generate trigger or question
          classification: isGenerateTrigger ? undefined : 'constraint',
          ackStatus: 'pending',
        };
        addMessage(userMessage);
        lastUserMsgIdRef.current = userMsgId; // Track for ack updates
        setSuggestedResponses([]); // Clear suggestions when user sends a message
        setLastUserMessage(trimmed); // Tier 11.12: Track for retry capability
        setIsLoading(true);

        // Create a message bubble for streaming tokens into
        const streamingMsgId = `a_stream_${Date.now()}`;
        addMessage({ id: streamingMsgId, role: 'assistant', content: '' });
        setStreamingMessageId(streamingMsgId);
        setHasReceivedFirstToken(false); // Reset for new streaming message

        // Use SSE streaming for real-time token display
        const body: Parameters<typeof streamGraphPlan>[0] = {
          message: trimmed,
          session_state: sessionState ?? undefined,
          // Pass suggestion_clicked when user clicked a suggestion chip
          // This enables LQA suggestion echo in the backend
          suggestion_clicked: options?.suggestionClicked,
        };

        // Create a promise that resolves when streaming completes
        await new Promise<void>((resolve) => {
          abortStreamRef.current = streamGraphPlan(body, {
            onToken: (token: string) => {
              // Mark that we've received the first token (hides typing/progress indicator)
              setHasReceivedFirstToken(true);
              // Dismiss delayed loader on first tangible output
              delayedLoader.onTangibleOutput();
              actionLoader.onTangibleOutput();
              // Append token to the streaming message
              appendToMessage(streamingMsgId, token);
            },
            onNodeStatus: (status: SSENodeStatusEvent['data']) => {
              if (status.status === 'started') {
                // Classify the action type for action-specific loader copy
                const classification = classifyNodeAction(status.node, triggerContext ?? undefined);

                // Only show action loader for recognized action types
                // This prevents loader from showing for pure chat, acknowledgment, validation, etc.
                if (classification) {
                  // Check if tiles exist for refresh_deals contextual copy
                  const tiles = useDocumentStore.getState().document?.tiles;
                  const hasTiles = tiles && Object.keys(tiles).length > 0;

                  actionLoader.startLoading(
                    classification.actionType,
                    status.estimated_duration_ms,
                    {
                      verticalType: classification.verticalType,
                      hasTiles,
                    }
                  );
                }

                // Also check legacy loader for backwards compatibility
                const shouldShow = shouldShowLoaderForNode(
                  status.node,
                  status.estimated_duration_ms
                );
                if (shouldShow) {
                  delayedLoader.startLoading(status.estimated_duration_ms);
                }

                // Always set nodeStatus for the progress component (when visible)
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
              delayedLoader.reset(); // Ensure loader is hidden
              actionLoader.reset(); // Reset action loader
              setTriggerContext(null); // Clear trigger context

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
                // Status is now shown via PlanStateBanner, not as a chat message
                filterMessages((msg) => msg.id !== streamingMsgId);
              } else if (isReadyToGenerate) {
                // Update the streaming message ID to use the ready prefix
                // so it can be removed when generation starts
                updateMessageId(streamingMsgId, `${READY_MESSAGE_ID_PREFIX}${streamingMsgId}`);
              }

              // --- Update user message with ack data for collapsible UI ---
              if (lastUserMsgIdRef.current && doc.ack_updates && doc.ack_updates.length > 0) {
                const userMsgId = lastUserMsgIdRef.current;
                // Update the user message with ack data
                updateMessage(userMsgId, {
                  ackStatus: doc.ack_status || 'applied',
                  ackUpdates: doc.ack_updates,
                });
                // Auto-collapse after delay (1200ms)
                setTimeout(() => {
                  setCollapsedMessages((prev) => new Set(prev).add(userMsgId));
                }, 1200);
              } else if (lastUserMsgIdRef.current) {
                // No ack updates - mark as no_change
                updateMessage(lastUserMsgIdRef.current, {
                  ackStatus: 'no_change',
                });
              }

              setIsLoading(false);
              resolve();
            },
            onError: (error: Error) => {
              setStreamingMessageId(null);
              setNodeStatus(null); // Clear strategy progress on error
              abortStreamRef.current = null; // Clear abort ref
              delayedLoader.reset(); // Ensure loader is hidden on error
              actionLoader.reset(); // Reset action loader
              setTriggerContext(null); // Clear trigger context
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
      [isLoading, onPlanResult, onGeneratePlanStart, selectedBranchId, sessionState, addMessage, appendToMessage, filterMessages, updateMessageId, updateMessage, setSessionState, delayedLoader, actionLoader, triggerContext, hasBranches]
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
    // Also don't show when loader is handling progress display
    const showTypingIndicator = isLoading && !hasReceivedFirstToken && !nodeStatus?.active && !delayedLoader.isVisible && !actionLoader.isVisible;
    // Show node progress only when:
    // 1. The action loader (policy-compliant) OR delayed loader (fallback) is visible
    // 2. We have active node status data to display
    // Action loader only shows for the 5 action types: generate_plan, update_plan, refresh_deals, create_itinerary, vertical_fetch
    const showNodeProgress = (actionLoader.isVisible || delayedLoader.isVisible) && nodeStatus?.active;

    return (
      <div
        ref={panelRef}
        className={`text-foreground flex ${panelHeightClass} min-h-0 w-full flex-col gap-4 transition-[min-height,max-height] duration-300 bg-transparent p-4`}
      >
        {/* Section header - minimal, no icon (per spec: brand once in global header) */}
        <div className="border-b border-border/40 pb-3">
          <span className="text-muted-foreground text-sm font-medium">
            Travel planner
          </span>
        </div>

        {/* Onboarding chips - state inspectors above input (per spec: fixed order) */}
        <OnboardingChips
          destination={destination}
          origin={origin}
          dateRange={dateRange}
          budget={budget}
          dateFlex={dateFlex}
          tripDuration={tripDuration}
          onDestinationClick={() => {
            const separator = input.trim() ? ', ' : '';
            setInput(prev => prev + separator + 'going to ');
            inputRef.current?.focus();
          }}
          onOriginClick={() => {
            const separator = input.trim() ? ', ' : '';
            setInput(prev => prev + separator + 'from ');
            inputRef.current?.focus();
          }}
          onDatesClick={() => {
            const separator = input.trim() ? ', ' : '';
            setInput(prev => prev + separator + 'dates are ');
            inputRef.current?.focus();
          }}
          onBudgetClick={() => {
            // Prefer opening budget input directly in TripDetailsForm
            if (onOpenBudgetInput) {
              onOpenBudgetInput();
            } else {
              // Fallback: insert text into chat
              const separator = input.trim() ? ', ' : '';
              setInput(prev => prev + separator + 'budget around ');
              inputRef.current?.focus();
            }
          }}
        />

        {/* Optional Refinements - directly under core chips, gated by destination + dates */}
        {tripInputs && bookingTypes && flightSettings && hotelSettings && activitySettings && transportSettings && (
          <OptionalRefinementsSection
            tripInputs={tripInputs}
            hasDestination={hasDestination}
            hasDates={hasDates}
            bookingTypes={bookingTypes}
            flightSettings={flightSettings}
            hotelSettings={hotelSettings}
            activitySettings={activitySettings}
            transportSettings={transportSettings}
            onUpdateBookingTypes={onUpdateBookingTypes!}
            onUpdateFlightSettings={onUpdateFlightSettings!}
            onUpdateHotelSettings={onUpdateHotelSettings!}
            onUpdateTransportSettings={onUpdateTransportSettings!}
            onAddActivity={onAddActivity!}
            onRemoveActivity={onRemoveActivity!}
            onUpdateAdults={onUpdateAdults!}
            onUpdateChildren={onUpdateChildren!}
            onToggleRequiresAssistance={onToggleRequiresAssistance!}
            llmUpdatedFields={llmUpdatedFields}
            onAcknowledgeLLMUpdate={onAcknowledgeLLMUpdate}
          />
        )}

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

                // Check if this user message should be collapsed
                const isCollapsed = isUserMessage && collapsedMessages.has(m.id) && m.ackUpdates && m.ackUpdates.length > 0;

                // Render collapsed row for eligible messages
                if (isCollapsed) {
                  return (
                    <div
                      key={m.id}
                      className="message-enter"
                      style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
                    >
                      <CollapsedMessageRow
                        ackStatus={m.ackStatus || 'applied'}
                        ackUpdates={m.ackUpdates || []}
                        isExpanded={false}
                        onToggle={() => {
                          setCollapsedMessages((prev) => {
                            const next = new Set(prev);
                            next.delete(m.id);
                            return next;
                          });
                        }}
                      />
                    </div>
                  );
                }

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
                  // Action-specific copy from actionLoader (policy-compliant)
                  actionTitle={actionLoader.isVisible ? actionLoader.title : undefined}
                  actionSubtext={actionLoader.isVisible ? actionLoader.subtext : undefined}
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
                    // Pass suggestion_clicked to enable LQA echo in backend
                    sendMessageCore(suggestion, { suggestionClicked: suggestion });
                  }}
                  className="text-xs px-3 py-1.5 rounded-full bg-gradient-to-b from-card to-muted/40 border border-border/60 hover:border-primary/40 text-foreground/70 hover:text-primary shadow-pill-accent hover:shadow-pill-hover transition-all duration-200 max-w-full truncate"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          <form onSubmit={handleSubmit} className="relative">
            {/* Static placeholder - only when input is empty and no user message */}
            {/* Calculation: 52px height - 4px border = 48px inner. (48px - 20px line-height) / 2 = 14px padding each side */}
            {!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory && (
              <div className="absolute top-0 left-0 right-0 px-4 py-[14px] pr-14 text-sm leading-5 text-muted-foreground/70 pointer-events-none whitespace-nowrap overflow-hidden text-ellipsis" aria-hidden="true">
                {isInputDisabledByPlanState
                  ? 'Updating...'
                  : !hasDestination
                    ? 'Enter destination'
                    : 'Add constraint, e.g. budget, dates...'}
              </div>
            )}
            <textarea
            ref={inputRef}
            disabled={isInputDisabledByPlanState}
            className={`border-input bg-muted/50 hover:bg-muted/60 text-foreground focus-visible:ring-primary/70 focus-visible:ring-offset-card w-full rounded-xl border-2 px-4 py-[14px] pr-14 text-sm leading-5 focus:outline-none focus:bg-muted/50 focus-visible:ring-2 focus-visible:ring-offset-1 transition-colors resize-none overflow-y-auto no-scrollbar min-h-[52px] max-h-[200px] scroll-mb-4 disabled:opacity-50 disabled:cursor-not-allowed ${!input.trim() && !hasUserMessage && !isLoading && !isLoadingHistory ? 'placeholder:text-transparent' : 'placeholder:text-muted-foreground/70'}`}
            placeholder={
              isInputDisabledByPlanState
                ? 'Updating...'
                : !hasDestination
                  ? 'Enter destination'
                  : 'Add constraint, e.g. budget, dates...'
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

          {/* Primary CTA - Generate plan (hidden after S2_STRATEGY_READY and during generation) */}
          {shouldShowLeftPanelGenerateCTA(planViewState) && generateState !== 'GENERATING' && (
            <div className="space-y-1">
              <button
                type="button"
                onClick={() => {
                  setGenerateTriggered(true);
                  sendMessageCore(GENERATE_PLAN_TRIGGER);
                }}
                disabled={generateState === 'DISABLED_INCOMPLETE'}
                className={cn(
                  "group w-full flex items-center justify-center gap-2 py-2 px-4 text-sm font-semibold rounded-full transition-all",
                  // DISABLED_INCOMPLETE - intentional locked state (opacity raised from 0.45 to 0.60 for WCAG)
                  generateState === 'DISABLED_INCOMPLETE' && "opacity-60 cursor-not-allowed text-muted-foreground/80 border border-muted-foreground/30 bg-muted/8",
                  // ENABLED_READY
                  generateState === 'ENABLED_READY' && cn(
                    "text-primary border border-primary/50 bg-primary/10 hover:bg-primary/15 hover:border-primary/70",
                    "dark:text-accent dark:border-accent/50 dark:bg-accent/15 dark:hover:bg-accent/25",
                    !hasAnimatedPulse && "cta-pulse-once"
                  ),
                  // GENERATED
                  generateState === 'GENERATED' && "text-muted-foreground border border-muted-foreground/30 bg-transparent hover:border-muted-foreground/50 hover:text-foreground"
                )}
              >
                {generateState === 'GENERATED' ? (
                  <>
                    <Sparkles className="h-4 w-4" />
                    <span>Regenerate plan</span>
                  </>
                ) : generateState === 'DISABLED_INCOMPLETE' ? (
                  <>
                    <Lock className="h-4 w-4 opacity-70" />
                    <span>Generate plan</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4 transition-transform group-hover:scale-110" />
                    <span>Generate plan</span>
                  </>
                )}
              </button>

              {/* Subtext per state */}
              {generateState === 'DISABLED_INCOMPLETE' && (
                <p className="text-center text-[11px] text-muted-foreground/50">
                  Set destination + dates to unlock.
                </p>
              )}
            </div>
          )}
        </div>

      </div>
    );
  }
);
