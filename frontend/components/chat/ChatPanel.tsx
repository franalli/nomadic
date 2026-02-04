// frontend/components/ChatPanel.tsx
'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { ArrowUp, RotateCcw, Sparkles } from 'lucide-react';
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

import { ExplorationProgress } from '@/components/plan/ExplorationProgress';
import {
  ActivitiesSheet,
  FlightsSheet,
  StaysSheet,
} from '@/components/plan/sheets';
import { UnifiedChipRow } from '@/components/plan/UnifiedChipRow';
import { useToast } from '@/components/ui/toast';
import { useMobileMode } from '@/contexts/MobileModeContext';
import { useActionLoader } from '@/hooks/useActionLoader';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { type SSENodeStatusEvent, streamGraphPlan, trackSuggestionClick } from '@/lib/api';
import { classifyNodeAction, shouldShowLoaderForNode } from '@/lib/loaderConfig';
import { preprocessSpecialistLinks } from '@/lib/specialistLinkParser';
import { cn } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import type { LLMUpdatableField } from '@/state/documentStore';
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
import type { ChatMessage } from '@/types/chat';
import {
  type ActivitySettings,
  type BookingTypes,
  type DocumentBranch,
  type DocumentTripInputs,
  type FlightSettings,
  type GraphPlanResponse,
  type HotelSettings,
  isBookingEnabled,
  type TransportSettings,
} from '@/types/document';
import type { TriggerContext } from '@/types/loader';
import type { PlanViewState } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

import { ChatSkeleton } from './ChatSkeleton';
import { CollapsedSetupSummary } from './CollapsedSetupSummary';
import { HoldToDeleteButton } from './HoldToDeleteButton';
import { MobileChatCompactHeader } from './MobileChatCompactHeader';
import { MobileSetupCollapsedHeader } from './MobileSetupCollapsedHeader';
// NodeProgress removed - replaced by Live Logic Status Pill above input
import { PlanModeHint } from './PlanModeHint';
import { type ActiveStatus,SmartLoader } from './SmartLoader';
import { SystemAckLine } from './SystemAckLine';
import { SystemReceipt } from './SystemReceipt';

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

// "Agency Voice" - Translates technical backend labels to travel concierge terminology
// This makes the loading states feel like a premium travel service, not a server
const AGENT_VOCAB: Record<string, string> = {
  // Technical -> Agency
  ROUTING: 'CONSULTING',
  VALIDATING: 'VERIFYING',
  CHECKING: 'REVIEWING',
  FETCHING: 'SEARCHING',
  GENERATING: 'DRAFTING',
  READING: 'REVIEWING',
  WRITING: 'DRAFTING',

  // Specific nouns
  CONSTRAINTS: 'LOGISTICS',
  MESSAGE: 'REQUEST',
  RESPONSE: 'ITINERARY',
};

// Helper to translate "ROUTING: DIVING" -> "CONSULTING: DIVING"
const toAgencyVoice = (rawLabel: string): string => {
  let text = rawLabel.toUpperCase();
  Object.entries(AGENT_VOCAB).forEach(([tech, agency]) => {
    text = text.replace(new RegExp(tech, 'g'), agency);
  });
  return text;
};

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
  destination: ['Tokyo', 'Paris', 'Bali'],
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
// Markdown components config - extracted to module level to prevent recreation on each render
// Full GFM support with professional styling for chat bubbles
const MARKDOWN_COMPONENTS = {
  // Paragraphs with proper spacing - mb-4 creates "Visual Islands" separation
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-4 last:mb-0 leading-relaxed">{children}</p>
  ),
  // Bold text with emphasis - zinc for key variables (dates, prices, locations)
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-zinc-900 dark:text-emerald-400">{children}</strong>
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
  // Links with proper styling - includes specialist deep link support
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    // Handle specialist: protocol links (deep links to specialist cards)
    if (href?.startsWith('specialist:')) {
      const specialistType = href.replace('specialist:', '');
      return (
        <button
          type="button"
          onClick={() => {
            // Dispatch custom event for specialist navigation
            window.dispatchEvent(
              new CustomEvent('specialist-navigate', {
                detail: { specialistType },
              })
            );
          }}
          className="text-zinc-900 dark:text-emerald-400 font-semibold hover:underline cursor-pointer inline"
        >
          {children}
        </button>
      );
    }
    // Regular external links
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline decoration-primary/50 underline-offset-2 hover:decoration-primary transition-colors"
      >
        {children}
      </a>
    );
  },
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
  /** Called when chat updates plan with existing itinerary - triggers auto-expand */
  onAutoExpandItinerary?: (options?: { forceFullRebuild?: boolean }) => void;
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
  /** Update activity settings callback */
  onUpdateActivitySettings?: (settings: Partial<ActivitySettings>) => void;
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
  /** Shared sheet opener - opens trip input sheets at common parent level */
  onOpenSheet?: (sheet: 'destination' | 'origin' | 'dates' | 'travelers' | 'budget') => void;
  /**
   * Whether a plan has ever been generated in this session.
   * When true, suppress "Generate plan" user messages and full assistant streaming
   * for regeneration triggers. Regeneration communicates via UI state instead.
   */
  hasEverHadPlan?: boolean;
  /**
   * Callback when user submits a message (before backend responds).
   * Used for optimistic UI - detect topics and show placeholder AgentCards.
   */
  onUserMessageSubmit?: (message: string) => void;
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
      onAutoExpandItinerary,
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
      dateFlex: _dateFlex,
      tripDuration: _tripDuration,
      // CTA gating flags
      hasDestination = false,
      canGeneratePlan: _canGeneratePlan = false,
      hasPlan: _hasPlan = false,
      // Optional Refinements Section props
      hasDates = false,
      tripInputs,
      bookingTypes,
      flightSettings,
      hotelSettings,
      activitySettings,
      transportSettings: _transportSettings,
      onUpdateBookingTypes,
      onUpdateFlightSettings,
      onUpdateHotelSettings,
      onUpdateActivitySettings,
      onUpdateTransportSettings: _onUpdateTransportSettings,
      onAddActivity: _onAddActivity,
      onRemoveActivity: _onRemoveActivity,
      onUpdateAdults: _onUpdateAdults,
      onUpdateChildren: _onUpdateChildren,
      onToggleRequiresAssistance: _onToggleRequiresAssistance,
      llmUpdatedFields: _llmUpdatedFields,
      onAcknowledgeLLMUpdate: _onAcknowledgeLLMUpdate,
      planViewState,
      onOpenBudgetInput: _onOpenBudgetInput,
      onOpenSheet,
      hasEverHadPlan,
      onUserMessageSubmit,
    } = props;

    // Reserved for future use
    void _onFreshStart;
    void _dateFlex;
    void _tripDuration;
    void _canGeneratePlan;
    void _hasPlan;
    void _transportSettings;
    void _onUpdateTransportSettings;
    void _onAddActivity;
    void _onRemoveActivity;
    void _onToggleRequiresAssistance;
    void _llmUpdatedFields;
    void _onAcknowledgeLLMUpdate;
    void _onOpenBudgetInput;
    void _onUpdateAdults;
    void _onUpdateChildren;

    // Derive input disabled state from planState (RESOLVING = disabled)
    const isInputDisabledByPlanState = planState === 'RESOLVING';

    // Use chat store for messages, history loading, and session state
    const messages = useChatStore((state) => state.messages);
    const addMessage = useChatStore((state) => state.addMessage);
    const updateMessage = useChatStore((state) => state.updateMessage);
    const appendToMessage = useChatStore((state) => state.appendToMessage);
    const updateMessageId = useChatStore((state) => state.updateMessageId);
    const filterMessages = useChatStore((state) => state.filterMessages);
    const collapseSetupMessages = useChatStore((state) => state.collapseSetupMessages);
    const isLoadingHistory = useChatStore((state) => state.isLoadingHistory);
    const loadHistory = useChatStore((state) => state.loadHistory);
    const sessionState = useChatStore((state) => state.sessionState);
    const setSessionState = useChatStore((state) => state.setSessionState);
    const deleteLastMessageFromStore = useChatStore((state) => state.deleteLastMessage);

    // Document store for restoring trip inputs on delete
    const restoreTripInputs = useDocumentStore((state) => state.restoreTripInputs);

    // Get desktop mode to determine if right panel with "Build Plan" button is visible
    const { isDesktop } = useMobileMode();

    const [input, setInput] = useState('');
    const [isDeleting, setIsDeleting] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
    const [hasReceivedFirstToken, setHasReceivedFirstToken] = useState(false);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    const [readyMessageShown, setReadyMessageShown] = useState(false);
    const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
    // Mobile Setup header collapse state - triggers when scroll > 50px
    const [isSetupHeaderCollapsed, setIsSetupHeaderCollapsed] = useState(false);
    // Track last user message ID for ack updates
    const lastUserMsgIdRef = useRef<string | null>(null);
    // Track last system event ID for updating status on completion
    const lastSystemEventIdRef = useRef<string | null>(null);
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

    // Smart Loader: current active status for single mutating line (DS Section 19.C)
    const [activeStatus, setActiveStatus] = useState<ActiveStatus | null>(null);

    // Module sheet open states (flights/stays/activities remain in ChatPanel)
    // Trip input sheets (destination/origin/dates/travelers/budget) are now in NomadicLanding
    const [flightsSheetOpen, setFlightsSheetOpen] = useState(false);
    const [staysSheetOpen, setStaysSheetOpen] = useState(false);
    const [activitiesSheetOpen, setActivitiesSheetOpen] = useState(false);

    // Toast for sheet saves
    const { toast } = useToast();

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
    // SYNC GUARD: Prevent duplicate message sends (React StrictMode safe)
    const isSendingRef = useRef(false);
    // Track previous specialist types and tile types for structural change detection
    // IMPORTANT: Use specialist_type (not title) for consistent comparison
    const prevSpecialistTypesRef = useRef<Set<string>>(new Set());
    const prevTileTypesRef = useRef<Set<string>>(new Set());

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
      const filtered = suggestions.filter((s) => {
        const isFieldCTA = /^(set|add|change)\s/i.test(s);
        if (!isFieldCTA) return true;
        const lower = s.toLowerCase();
        if (seen.has(lower)) return false;
        seen.add(lower);
        return true;
      });

      // On desktop, filter out "Build Plan" chip since the right panel has that CTA
      // Keep one primary CTA at a time to avoid competing buttons
      if (isDesktop) {
        return filtered.filter((s) => s.toLowerCase() !== 'build plan');
      }
      return filtered;
    }, [suggestedResponses, isLoading, hasBranches, missingFields, isDesktop]);

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
    // Also track scroll position for mobile setup header collapse (threshold: 50px)
    const handleScroll = useCallback(() => {
      isUserScrolledUpRef.current = !isNearBottom();

      // Mobile setup header collapse: collapse when scrolled past 50px
      const container = scrollContainerRef.current;
      if (container && !isDesktop) {
        const shouldCollapse = container.scrollTop > 50;
        setIsSetupHeaderCollapsed(shouldCollapse);
      }
    }, [isNearBottom, isDesktop]);

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
      isSendingRef.current = false; // Clear send guard
      delayedLoader.reset(); // Clear delayed loader on interrupt
    }, [streamingMessageId, messages, updateMessage, delayedLoader]);

    // Scroll panel into view and focus input when response finishes (isLoading: true -> false)
    useEffect(() => {
      if (!prevIsLoadingRef.current && isLoading) {
        // Scroll to bottom when loading STARTS so Logic Terminal is visible
        // (especially important on mobile where keyboard may cover the bottom)
        scrollToBottom(true);
      } else if (prevIsLoadingRef.current && !isLoading) {
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

    // Smart Loader: Single mutating status line (DS Section 19.C)
    // Uses "Agency Voice" to translate technical terms to travel concierge language
    useEffect(() => {
      if (!nodeStatus || !isLoading) return;

      // 1. HANDLE LOGIC REVEAL (The "Brain" Event)
      // Backend sends: { node: "logic_reveal", label: "ROUTING: DIVING" }
      // Frontend shows: "CONSULTING: DIVING"
      if (nodeStatus.node === 'logic_reveal') {
        setActiveStatus((prev) =>
          prev
            ? {
                ...prev,
                detail: toAgencyVoice(nodeStatus.label), // Translate to agency speak
              }
            : null
        );
        return;
      }

      // 2. STANDARD STATUS UPDATE
      // Backend sends: { node: "architect", label: "Reading message...", iconKey: "building" }
      // Frontend shows: "REVIEWING REQUEST"
      setActiveStatus({
        label: toAgencyVoice(nodeStatus.label.replace(/\.+$/, '')),
        icon_key: nodeStatus.iconKey || 'default',
        detail: undefined, // Reset detail on new node
      });
    }, [nodeStatus, isLoading]);

    const sendMessageCore = useCallback(
      async (messageText: string, options?: { suggestionClicked?: string }) => {
        const trimmed = messageText.trim();

        // SYNC GUARD: Prevent duplicate sends (React StrictMode safe)
        if (isSendingRef.current) {
          console.log('[ChatPanel] ⏭️ Skipping - already sending (ref guard)');
          return;
        }

        // Check for generate trigger FIRST (before isLoading guard)
        const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER || trimmed.toLowerCase() === 'build plan';

        // DEBUG: Log all sendMessage calls
        console.log('[ChatPanel] sendMessageCore called', {
          message: trimmed.slice(0, 50),
          isGenerateTrigger,
          isLoading,
          destination: useDocumentStore.getState().document?.trip_inputs?.destination,
        });

        // For regeneration triggers, we MUST process even if currently loading
        // This allows REFRESH to interrupt ongoing operations
        if (isGenerateTrigger && isLoading) {
          console.log('[ChatPanel] ⚠️ Forcing regeneration trigger despite isLoading=true');
          // Abort any ongoing stream before starting new one
          if (abortStreamRef.current) {
            console.log('[ChatPanel] 🛑 Aborting previous stream');
            abortStreamRef.current();
            abortStreamRef.current = null;
          }
          // Don't return - let it through
        } else if (!trimmed || isLoading) {
          console.log('[ChatPanel] ⏭️ Skipping - empty or loading');
          return;
        }

        // Reset Smart Loader for new message
        setActiveStatus(null);

        // Set trigger context for action classification
        // This helps classify the node_status events that follow
        setTriggerContext({
          isGeneratePlanTrigger: isGenerateTrigger,
          // If we already have branches and this isn't a generate trigger, it's a constraint change
          isConstraintChange: hasBranches && !isGenerateTrigger,
        });

        // Notify parent that generate plan has started (for loading screen)
        if (isGenerateTrigger) {
          setGenerateTriggered(true);
          onGeneratePlanStart?.();
        }

        // Silent plan mode: suppress assistant streaming from chat
        // ONLY suppress when Build Plan is clicked - chat should be conversational during Setup
        // Plan info should display on the right panel (tiles, strategy_sections), NOT in chat
        const isSilentPlanGeneration = isGenerateTrigger;

        // Handle message creation based on type
        const userMsgId = `u_${Date.now()}`;
        if (isGenerateTrigger && !isSilentPlanGeneration) {
          // System event line for "Build Plan" (not a user bubble)
          const systemEventId = `sys_${Date.now()}`;
          addMessage({
            id: systemEventId,
            role: 'system',
            content: '',
            displayMode: 'ack_line',
            ackStatus: 'pending',
          });
          lastSystemEventIdRef.current = systemEventId;
        } else if (!isSilentPlanGeneration) {
          // Regular user message
          const userMessage: ChatMessage = {
            id: userMsgId,
            role: 'user',
            content: trimmed,
            classification: 'constraint',
            ackStatus: 'pending',
          };
          addMessage(userMessage);
          lastUserMsgIdRef.current = userMsgId; // Track for ack updates

          // Notify parent of user message for optimistic topic detection
          onUserMessageSubmit?.(trimmed);
        }
        setSuggestedResponses([]); // Clear suggestions when user sends a message
        setLastUserMessage(trimmed); // Tier 11.12: Track for retry capability
        setIsLoading(true);
        isSendingRef.current = true; // Set ref to prevent duplicate sends

        // Create a message bubble for streaming tokens into - but NOT for plan generation
        // Plan content should appear on right panel, not in chat
        const streamingMsgId = `a_stream_${Date.now()}`;
        if (!isSilentPlanGeneration) {
          addMessage({ id: streamingMsgId, role: 'assistant', content: '' });
          setStreamingMessageId(streamingMsgId);
          setHasReceivedFirstToken(false); // Reset for new streaming message
        }

        // Use SSE streaming for real-time token display
        const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;
        const body: Parameters<typeof streamGraphPlan>[0] = {
          message: trimmed,
          session_state: sessionState ?? undefined,
          // Pass suggestion_clicked when user clicked a suggestion chip
          // This enables LQA suggestion echo in the backend
          suggestion_clicked: options?.suggestionClicked,
          // CRITICAL: For regeneration triggers, pass current frontend trip_inputs
          // This ensures backend uses the latest destination/dates, not cached state
          // Fixes race condition where user changes destination then clicks Refresh
          ...(isGenerateTrigger && {
            trip_inputs: currentTripInputs ?? undefined,
          }),
        };

        // DEBUG: Log API payload for regeneration triggers
        if (isGenerateTrigger) {
          console.log('[ChatPanel] 📤 Sending GENERATE_PLAN_TRIGGER to API', {
            destination: body.trip_inputs?.destination,
            start_date: body.trip_inputs?.start_date,
            end_date: body.trip_inputs?.end_date,
            hasTripInputs: !!body.trip_inputs,
          });
        }

        // Create a promise that resolves when streaming completes
        await new Promise<void>((resolve) => {
          abortStreamRef.current = streamGraphPlan(body, {
            onToken: (token: string) => {
              // Mark that we've received the first token (hides typing/progress indicator)
              setHasReceivedFirstToken(true);
              // Dismiss delayed loader on first tangible output
              delayedLoader.onTangibleOutput();
              actionLoader.onTangibleOutput();
              // Append token to the streaming message (skip for plan generation - content goes to right panel)
              if (!isSilentPlanGeneration) {
                appendToMessage(streamingMsgId, token);
              }
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
              } else if (status.status === 'completed') {
                // Clear node status when completed
                setNodeStatus(null);
                delayedLoader.reset();
                actionLoader.reset();
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

              // Capture previous state BEFORE onPlanResult updates the store
              const prevSpecialistTypes = prevSpecialistTypesRef.current;
              const prevTileTypes = prevTileTypesRef.current;

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

              // B2: Auto-focus right panel when tiles arrive
              const hasTiles = doc.tiles && Object.keys(doc.tiles).length > 0;

              // DEBUG: Log response to understand tile/state issue
              console.log('[ChatPanel] Response received:', {
                hasTiles,
                tileCount: doc.tiles ? Object.keys(doc.tiles).length : 0,
                tileIds: doc.tiles ? Object.keys(doc.tiles).slice(0, 5) : [],
                plan_view_state: doc.plan_view_state,
                hasDestination: Boolean(doc.trip_inputs?.destination),
                destination: doc.trip_inputs?.destination,
                // Strategy sections debug
                strategy_sections_count: doc.strategy_sections?.length ?? 0,
                strategy_sections: doc.strategy_sections,
                executed_strategy_topics: doc.executed_strategy_topics,
                pending_strategy_topics: doc.pending_strategy_topics,
              });

              if (hasTiles) {
                // On mobile: scroll right panel into view
                const rightPanel = document.getElementById('plan-panel');
                if (rightPanel && window.innerWidth < 768) {
                  rightPanel.scrollIntoView({ behavior: 'smooth' });
                }
              }

              const isReadyToGenerate = doc.ready_to_generate === true;

              // Update suggested responses from LLM (if provided)
              setSuggestedResponses(doc.suggested_responses || []);

              // Origin update from chat (e.g., "from rome") is handled by backend
              // Backend routes through LogisticsNode to fetch flights automatically
              // Tiles (including flights) come back in the response
              if (doc.origin_just_set && doc.trip_inputs?.origin) {
                console.log('[ChatPanel] Origin set via chat:', doc.trip_inputs.origin, '- flights fetched by backend');
              }

              // AUTO-EXPAND: Detect structural changes that require itinerary rebuild
              // Check STORE for existing itinerary (response may not include day_cards if not rebuilt)
              const storeDoc = useDocumentStore.getState().document;
              const hasItinerary = (storeDoc?.day_cards?.length ?? 0) > 0;

              // New state from response - MUST use specialist_type (not title) for consistent comparison
              // Filter out undefined specialist_types (shouldn't happen, but TypeScript safety)
              const newSpecialistTypes = (doc.strategy_sections?.map(s => s.specialist_type).filter((t): t is string => !!t)) ?? [];
              const newTileTypes = new Set(Object.values(doc.tiles ?? {}).map(t => t.type));

              // Detect new content
              const hasNewSpecialist = newSpecialistTypes.some(t => !prevSpecialistTypes.has(t));
              const hasNewTileType = [...newTileTypes].some(t => !prevTileTypes.has(t));

              // Update refs for next comparison (use specialist_type consistently)
              prevSpecialistTypesRef.current = new Set(newSpecialistTypes);
              prevTileTypesRef.current = newTileTypes;

              // Auto-expand if structural change detected (gated behind hasItinerary)
              if (hasItinerary && (hasNewSpecialist || hasNewTileType) && !isSilentPlanGeneration) {
                console.log('[ChatPanel] Structural change detected - auto-expanding...', {
                  hasNewSpecialist,
                  hasNewTileType,
                  prevSpecialists: [...prevSpecialistTypes],
                  newSpecialists: newSpecialistTypes,
                });
                setTimeout(() => {
                  onAutoExpandItinerary?.({ forceFullRebuild: true });
                }, 100);
              } else if (hasItinerary && !hasNewSpecialist && !hasNewTileType) {
                console.log('[ChatPanel] Additive change only, itinerary preserved');
              }

              // Only filter streaming message when Build Plan was clicked (silent mode)
              // During Setup, chat should be conversational - show all messages
              if (isSilentPlanGeneration) {
                // Build Plan clicked - remove streaming message, plan goes to right panel
                filterMessages((msg) => msg.id !== streamingMsgId);

                // Collapse any existing Setup messages
                const summaryParts: string[] = [];
                const newTripInputs = doc.trip_inputs;
                if (newTripInputs?.destination) {
                  summaryParts.push(newTripInputs.destination);
                }
                if (newTripInputs?.start_date) {
                  summaryParts.push(newTripInputs.start_date);
                }
                if (newTripInputs?.adults) {
                  summaryParts.push(`${newTripInputs.adults} adult${newTripInputs.adults > 1 ? 's' : ''}`);
                }
                const summaryText = summaryParts.length > 0
                  ? `Setup complete: ${summaryParts.join(' · ')}`
                  : 'Setup conversation';
                collapseSetupMessages(
                  summaryText,
                  doc.trip_inputs,
                  doc.executed_strategy_topics
                );
              } else {
                // No plan content yet - handle as regular chat message
                if (isReadyToGenerate) {
                  // Update the streaming message ID to use the ready prefix
                  // so it can be removed when generation starts
                  updateMessageId(streamingMsgId, `${READY_MESSAGE_ID_PREFIX}${streamingMsgId}`);
                }

                // --- Update user message with ack data for SystemReceipt display ---
                // "Command & Receipt" pattern: user message stays visible, receipt shows below
                if (lastUserMsgIdRef.current && doc.ack_updates && doc.ack_updates.length > 0) {
                  const userMsgId = lastUserMsgIdRef.current;
                  // Update the user message with ack data (no auto-collapse)
                  updateMessage(userMsgId, {
                    ackStatus: doc.ack_status || 'applied',
                    ackUpdates: doc.ack_updates,
                  });
                } else if (lastUserMsgIdRef.current) {
                  // No ack updates - mark as no_change
                  updateMessage(lastUserMsgIdRef.current, {
                    ackStatus: 'no_change',
                  });
                }
              }

              setIsLoading(false);
              isSendingRef.current = false; // Clear send guard
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

              // Replace streaming message with specific error message (skip in silent mode)
              if (!isSilentPlanGeneration) {
                const errorMessage = getErrorMessage(error);
                const errorMsgId = `a_err_${Date.now()}`;
                updateMessageId(streamingMsgId, errorMsgId);
                updateMessage(errorMsgId, { content: errorMessage });
              }

              setIsLoading(false);
              isSendingRef.current = false; // Clear send guard
              resolve(); // Resolve instead of reject to prevent unhandled promise rejection
            },
          });
        });
      },
      [isLoading, onPlanResult, onGeneratePlanStart, selectedBranchId, sessionState, addMessage, appendToMessage, filterMessages, updateMessageId, updateMessage, setSessionState, delayedLoader, actionLoader, triggerContext, hasBranches, collapseSetupMessages, hasEverHadPlan, onUserMessageSubmit, tripInputs?.adults, tripInputs?.destination, tripInputs?.start_date]
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

    // Count user messages for exploration progress indicator
    const userMessageCount = messages.filter((m) => m.role === 'user').length;

    // Exploration mode: user has destination, asked questions, but no dates/plan yet
    const isExplorationMode = Boolean(
      hasDestination &&
      !hasDates &&
      !hasBranches &&
      userMessageCount > 0
    );

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
        // Always show system messages and messages with special displayMode
        if (m.role === 'system' || m.displayMode === 'ack_line' || m.displayMode === 'collapsed_summary') {
          return true;
        }
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
      .flatMap((m): (ChatMessage & { _isPartOfSplit?: boolean; _isFirstPart?: boolean; _isLastPart?: boolean })[] => {
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
        return [m];
      });

    // Note: Three-dot typing indicator removed - Live Logic Status Pill above input is the only loading indicator

    return (
      <div
        ref={panelRef}
        className={`text-foreground flex ${panelHeightClass} min-h-0 w-full flex-col gap-4 transition-[min-height,max-height] duration-300 bg-transparent p-4`}
      >
        {/* Mobile Setup Header - Collapsed/Expanded state based on scroll */}
        {/* When scrolled > 50px, collapse to compact glass bar */}
        {!isDesktop && planViewState === 'S0_BOOTSTRAP' && (
          <AnimatePresence mode="wait">
            {isSetupHeaderCollapsed ? (
              <MobileSetupCollapsedHeader
                key="collapsed-header"
                tripInputs={tripInputs}
                dateRange={dateRange}
                onExpand={() => {
                  // Scroll back to top to expand
                  scrollContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
                }}
              />
            ) : (
              <motion.div
                key="hero-banner"
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}
                className="relative -mx-4 -mt-4 mb-0 w-[calc(100%+2rem)] overflow-hidden border-b border-border/30"
              >
                {/* Topo pattern layer - boosted opacity for retina mobile visibility */}
                <div
                  className="absolute inset-0 animate-topo-drift opacity-[0.12] dark:opacity-[0.08]"
                  style={{
                    maskImage: 'url("/assets/contours.svg")',
                    WebkitMaskImage: 'url("/assets/contours.svg")',
                    maskSize: '350px',
                    WebkitMaskSize: '350px',
                    maskRepeat: 'repeat',
                    WebkitMaskRepeat: 'repeat',
                    maskPosition: '0% 0%',
                    WebkitMaskPosition: '0% 0%',
                    willChange: '-webkit-mask-position, mask-position',
                  }}
                >
                  {/* Black background for max contrast in light mode */}
                  <div className="absolute inset-0 bg-black dark:bg-white" />
                </div>

                {/* Content - padding-based height for tighter fit */}
                <div className="relative z-10 flex flex-col items-center justify-center text-center px-4 py-6">
                  <h1 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-white">
                    {/* Dynamic headline based on trip input progress */}
                    {!destination ? 'Where to next?' :
                     !dateRange ? 'When would you like to go?' :
                     !tripInputs?.adults ? 'Who\'s traveling?' :
                     'Ready to build your plan'}
                  </h1>
                  {/* Terminal cursor indicator - classic blink */}
                  {/* Light: "Typewriter Ink" (Jet Black) | Dark: "System Pulse" (Emerald Glow) */}
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span className="font-mono text-[9px] uppercase tracking-[0.12em] font-bold text-zinc-950 dark:text-emerald-500 dark:drop-shadow-[0_0_8px_rgba(16,185,129,0.5)]">
                      {/* Contextual status message */}
                      {!destination ? 'Awaiting Input' :
                       !dateRange ? 'Set Dates' :
                       !tripInputs?.adults ? 'Add Travelers' :
                       'Generating Plan'}
                    </span>
                    <div className="w-1 h-1.5 bg-zinc-950 dark:bg-emerald-500 animate-terminal-blink rounded-sm dark:shadow-[0_0_6px_rgba(16,185,129,0.6)]" />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}

        {/* Mobile Compact Header - shown after plan generation (replaces hero) */}
        {/* This is the "morphing tab" - Chat tab transforms from Setup to Chat mode */}
        {!isDesktop && hasEverHadPlan && planViewState !== 'S0_BOOTSTRAP' && (
          <MobileChatCompactHeader
            tripInputs={tripInputs}
            planState={planState}
            onOpenSheet={onOpenSheet}
          />
        )}

        {/* Unified Chip Row - two-row layout: core constraints + module toggles */}
        {/* In S1+, header pills are the ONLY interactive surface for trip inputs */}
        {/* Show UnifiedChipRow in S0 only (bootstrap phase) - hide when mobile header is collapsed */}
        {planViewState === 'S0_BOOTSTRAP' && (!isSetupHeaderCollapsed || isDesktop) && (
          <UnifiedChipRow
            destination={destination}
            origin={origin}
            dateRange={dateRange}
            travelers={tripInputs?.adults ? `${tripInputs.adults} adult${tripInputs.adults > 1 ? 's' : ''}${tripInputs.children ? `, ${tripInputs.children} child${tripInputs.children > 1 ? 'ren' : ''}` : ''}` : undefined}
            budget={budget}
            bookingTypes={bookingTypes || DEFAULT_BOOKING_TYPES}
            flightSettings={flightSettings}
            hotelSettings={hotelSettings}
            activitySettings={activitySettings}
            onOpenDestination={() => onOpenSheet?.('destination')}
            onOpenOrigin={() => onOpenSheet?.('origin')}
            onOpenDates={() => onOpenSheet?.('dates')}
            onOpenTravelers={() => onOpenSheet?.('travelers')}
            onOpenBudget={() => onOpenSheet?.('budget')}
            onOpenFlights={() => setFlightsSheetOpen(true)}
            onOpenStays={() => setStaysSheetOpen(true)}
            onOpenActivities={() => setActivitiesSheetOpen(true)}
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
              {/* Plan mode hint - shown after Setup→Plan transition */}
              {planViewState !== 'S0_BOOTSTRAP' && hasEverHadPlan && (
                <PlanModeHint
                  hasSetupHistory={messages.some((m) => m.displayMode === 'collapsed_summary')}
                />
              )}

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

                // Setup phase messages should appear faded (past tense visual treatment)
                const isSetupPhase = m.phase === 'setup';

                // Check if this user message has ack updates (for SystemReceipt display)
                const hasAckUpdates = isUserMessage && m.ackUpdates && m.ackUpdates.length > 0;

                // Render system ack line for system messages or ack_line displayMode
                if (m.role === 'system' || m.displayMode === 'ack_line') {
                  return (
                    <div
                      key={m.id}
                      className="message-enter"
                      style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
                    >
                      <SystemAckLine
                        status={m.ackStatus || 'applied'}
                        updates={m.ackUpdates}
                        isPending={m.ackStatus === 'pending'}
                      />
                    </div>
                  );
                }

                // Render collapsed Setup summary
                // On mobile post-plan, use compact variant (thin divider style)
                if (m.displayMode === 'collapsed_summary') {
                  return (
                    <div
                      key={m.id}
                      className="message-enter"
                      style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
                    >
                      <CollapsedSetupSummary
                        summaryText={m.summaryText || 'Setup conversation'}
                        tripInputsSnapshot={m.tripInputsSnapshot}
                        executedTopicsSnapshot={m.executedTopicsSnapshot}
                        variant={!isDesktop && hasEverHadPlan ? 'compact' : 'card'}
                      />
                    </div>
                  );
                }

                return (
                  <div
                    key={m.id}
                    className={`${isUserMessage ? 'text-right' : 'text-left'} message-enter ${spacingClass} ${isSetupPhase ? 'opacity-60' : ''}`}
                    style={{ animationDelay: `${Math.min(idx * 30, 150)}ms` }}
                  >
                    {/* Relative container for absolute delete button positioning */}
                    <div className={`inline-block relative max-w-[85%] ${showDeleteButton ? 'group/msg' : ''}`}>
                      {/* "Command & Receipt" pattern: User message + SystemReceipt below */}
                      {isUserMessage ? (
                        <div className="flex flex-col items-end">
                          {/* The Commander (User Bubble) */}
                          <div
                            className={cn(
                              // Shape: Speech bubble with sharp bottom-right corner
                              'rounded-2xl rounded-br-md px-4 py-2.5 text-left transition-all',
                              // Light Mode: Solid Black (The Commander)
                              'bg-zinc-900 text-white border border-zinc-900',
                              'shadow-md hover:shadow-lg hover:-translate-y-0.5',
                              'hover:bg-zinc-800 hover:border-zinc-800',
                              // Dark Mode: Solid White (Maximum Contrast Signal)
                              'dark:bg-white dark:text-zinc-950 dark:border-white',
                              'dark:shadow-[0_0_20px_-5px_rgba(255,255,255,0.3)]',
                              'dark:hover:bg-zinc-100'
                            )}
                          >
                            {m.content}
                          </div>
                          {/* The System Receipt - DS Section 19 */}
                          {hasAckUpdates && (
                            <SystemReceipt
                              ackStatus={m.ackStatus || 'applied'}
                              ackUpdates={m.ackUpdates || []}
                              mode={m.phase}
                            />
                          )}
                        </div>
                      ) : (
                        /* Assistant message */
                        <div
                          className={cn(
                            // Shape: Speech bubble with sharp bottom-left corner
                            'rounded-2xl rounded-bl-sm px-4 py-2.5 transition-all',
                            // Light Mode: Glass effect
                            'bg-white/80 backdrop-blur-sm',
                            'border border-zinc-200',
                            'shadow-sm',
                            'hover:shadow-md hover:-translate-y-0.5',
                            // Dark Mode: Dark Glass (The System/Infrastructure)
                            'dark:bg-white/5 dark:backdrop-blur-sm',
                            'dark:border-white/10',
                            'dark:shadow-none',
                            // Text: High contrast
                            'text-zinc-700 dark:text-zinc-300',
                            isStreaming && 'typing-pulse'
                          )}
                        >
                          <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
                            {preprocessSpecialistLinks(m.content)}
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
                        </div>
                      )}
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
              {/* Smart Loader: Single mutating status line - DS Section 19.C */}
              {/* Shows current processing state with dynamic icon */}
              {isLoading && activeStatus && visibleMessages[visibleMessages.length - 1]?.role === 'user' && (
                <SmartLoader status={activeStatus} />
              )}
              {/* Invisible sentinel for smooth scroll-to-bottom */}
              <div ref={bottomSentinelRef} aria-hidden="true" className="h-px" />
            </>
          )}
        </div>

        {/* Input area with suggestions - grouped together at bottom */}
        <div className="mt-auto space-y-3 pb-0">
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
              className="flex flex-wrap justify-center gap-2 pt-3 pb-1 px-2"
            >
              {effectiveSuggestions.map((suggestion, idx) => {
                // Detect planning-trigger suggestions (e.g., "Plan Bali trip", "Let's plan it")
                const isPlanningTrigger = /\bplan\b/i.test(suggestion) || suggestion.toLowerCase().includes("let's plan");

                return (
                  <button
                    key={`sugg-${suggestion.slice(0, 20)}-${idx}`}
                    type="button"
                    onClick={() => {
                      // Track suggestion click for analytics (fire-and-forget)
                      trackSuggestionClick(suggestion, idx);
                      // Pass suggestion_clicked to enable LQA echo in backend
                      sendMessageCore(suggestion, { suggestionClicked: suggestion });
                    }}
                    className={cn(
                      'px-4 py-2.5 rounded-lg',
                      'text-xs font-bold uppercase tracking-wide',
                      'transition-all duration-150 active:scale-95',
                      'max-w-full truncate',
                      // Planning trigger chips: emerald highlight to draw attention
                      isPlanningTrigger ? [
                        'bg-emerald-50 dark:bg-emerald-950/30',
                        'border-2 border-emerald-500/40 dark:border-emerald-500/30',
                        'text-emerald-700 dark:text-emerald-400',
                        'shadow-[0_0_12px_-3px_rgba(16,185,129,0.2)]',
                        'hover:bg-emerald-100 hover:border-emerald-500 hover:shadow-md',
                        'dark:hover:bg-emerald-900/40 dark:hover:border-emerald-400/50',
                      ] : [
                        // DS Tactile Rule: border-2 for visible buttons, snap-to-black hover
                        'bg-white dark:bg-white/5',
                        'border-2 border-zinc-200 dark:border-white/15',
                        'text-zinc-600 dark:text-zinc-400',
                        'hover:border-zinc-900 hover:bg-zinc-50 hover:text-zinc-900',
                        'dark:hover:bg-white/10 dark:hover:border-white/40 dark:hover:text-white',
                      ]
                    )}
                  >
                    {/* Sparkle icon for planning triggers */}
                    {isPlanningTrigger && <Sparkles className="w-3 h-3 mr-1.5 inline-block" />}
                    {suggestion}
                  </button>
                );
              })}
            </div>
          )}

          {/* Exploration Progress - shows after 3+ questions during exploration mode */}
          {isExplorationMode && userMessageCount >= 3 && !isLoading && (
            <ExplorationProgress
              questionCount={userMessageCount}
              destination={destination}
              onPlanNow={() => sendMessageCore("Let's plan my trip!")}
              className="mx-4 mb-3"
            />
          )}

          {/* Action Bar: Unified Capsule Design with "Living Void" Effect */}
          {/* Input and button merged into one continuous capsule (like Perplexity/ChatGPT) */}
          {/* During AI processing: the input BECOMES the status indicator (emerald glow + pulse) */}
          <div
            className={cn(
              'relative flex items-center w-full h-14 rounded-[28px] transition-all duration-300',
              'bg-zinc-50 dark:bg-black/40',
              // Priority 1: "Living Void" - AI Processing state
              isLoading && nodeStatus?.node
                ? [
                    'border border-emerald-500/50 dark:border-emerald-500/40',
                    'shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)] dark:shadow-[0_0_25px_-5px_rgba(16,185,129,0.3)]',
                    'animate-pulse',
                  ]
                // Priority 2: Ready to Generate highlight
                : readyToGenerate && !input.trim() && planViewState === 'S0_BOOTSTRAP' && !isGenerating && !hasBranches
                  ? 'border border-emerald-500/50 ring-1 ring-emerald-500/30 dark:shadow-[0_0_20px_-5px_rgba(16,185,129,0.2)]'
                  // Default state
                  : [
                      'shadow-[0_8px_30px_-8px_rgba(0,0,0,0.08)] dark:shadow-[0_8px_30px_-8px_rgba(0,0,0,0.3)]',
                      'border border-zinc-200 dark:border-white/10',
                    ]
            )}
          >
            {/* Input Field - takes remaining space */}
            {/* Note: Status text removed - Logic Terminal in chat list is the single source of truth (DS Section 19.C) */}
            <form onSubmit={handleSubmit} className="flex-1 h-full">
              <textarea
                ref={inputRef}
                disabled={isInputDisabledByPlanState}
                className="w-full h-full bg-transparent text-zinc-900 dark:text-white pl-6 pr-2 py-4 text-sm font-medium leading-5 resize-none overflow-hidden border-none outline-none focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
                placeholder={
                  isInputDisabledByPlanState
                    ? 'Updating...'
                    : readyToGenerate
                      ? 'Type to refine...'
                      : !hasDestination
                        ? 'Where to?'
                        : 'Tell me more...'
                }
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
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
            </form>

            {/* Button - inside the capsule */}
            <div className="pr-1.5 py-1.5 flex-shrink-0">
              {isLoading && hasReceivedFirstToken ? (
                // Stop streaming button - minimal monochrome (not red - that's for errors)
                <button
                  type="button"
                  onClick={handleStopStreaming}
                  className={cn(
                    'h-11 w-11 flex items-center justify-center rounded-[22px] transition-all hover:scale-105 active:scale-95',
                    'bg-zinc-200 dark:bg-white/10',
                    'hover:bg-zinc-300 dark:hover:bg-white/20',
                    'border border-zinc-300 dark:border-white/10'
                  )}
                  title="Stop"
                >
                  {/* Minimal square icon - matches theme */}
                  <div className="w-3 h-3 bg-zinc-900 dark:bg-white rounded-[2px]" />
                </button>
              ) : (
                // SEND STATE: Arrow button inside capsule
                <button
                  type="button"
                  onClick={(e) => input.trim() && handleSubmit(e as unknown as React.FormEvent)}
                  disabled={isLoading || !input.trim()}
                  className={cn(
                    'h-11 w-11 flex items-center justify-center rounded-[22px] transition-all duration-300',
                    input.trim() && !isLoading
                      ? 'bg-zinc-900 text-white hover:bg-zinc-800 hover:scale-105 active:scale-95 dark:bg-emerald-600 dark:hover:bg-emerald-500 dark:shadow-[0_0_15px_-3px_rgba(16,185,129,0.4)]'
                      : 'bg-zinc-200 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-600'
                  )}
                  title="Send message (Enter)"
                >
                  <ArrowUp className="h-5 w-5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Module sheets (flights/stays/activities) - control booking types */}
        {/* Trip input sheets (destination/origin/dates/travelers/budget) are in NomadicLanding */}
        <FlightsSheet
          open={flightsSheetOpen}
          onOpenChange={setFlightsSheetOpen}
          enabled={isBookingEnabled(bookingTypes?.flights)}
          settings={flightSettings || { round_trip: true, cabin_class: 'economy', direct_only: false }}
          hasOrigin={!!origin}
          hasDestination={hasDestination}
          hasDates={hasDates}
          onToggle={(enabled) => {
            if (onUpdateBookingTypes) {
              onUpdateBookingTypes({ flights: enabled ? 'on' : 'off' });
            }
            toast(enabled ? 'Flights included' : 'Flights removed');
          }}
          onSaveSettings={(settings) => {
            if (onUpdateFlightSettings) {
              onUpdateFlightSettings(settings);
            }
            toast('Flight preferences saved');
          }}
          onOpenOrigin={() => {
            setFlightsSheetOpen(false);
            setTimeout(() => onOpenSheet?.('origin'), 150);
          }}
          onOpenDestination={() => {
            setFlightsSheetOpen(false);
            setTimeout(() => onOpenSheet?.('destination'), 150);
          }}
          onOpenDates={() => {
            setFlightsSheetOpen(false);
            setTimeout(() => onOpenSheet?.('dates'), 150);
          }}
        />

        <StaysSheet
          open={staysSheetOpen}
          onOpenChange={setStaysSheetOpen}
          enabled={isBookingEnabled(bookingTypes?.hotels)}
          settings={hotelSettings || { min_stars: 0, amenities: [] }}
          hasDestination={hasDestination}
          hasDates={hasDates}
          onToggle={(enabled) => {
            if (onUpdateBookingTypes) {
              onUpdateBookingTypes({ hotels: enabled ? 'on' : 'off' });
            }
            toast(enabled ? 'Stays included' : 'Stays removed');
          }}
          onSaveSettings={(settings) => {
            if (onUpdateHotelSettings) {
              onUpdateHotelSettings(settings);
            }
            toast('Stay preferences saved');
          }}
          onOpenDestination={() => {
            setStaysSheetOpen(false);
            setTimeout(() => onOpenSheet?.('destination'), 150);
          }}
          onOpenDates={() => {
            setStaysSheetOpen(false);
            setTimeout(() => onOpenSheet?.('dates'), 150);
          }}
        />

        <ActivitiesSheet
          open={activitiesSheetOpen}
          onOpenChange={setActivitiesSheetOpen}
          enabled={isBookingEnabled(bookingTypes?.activities)}
          settings={activitySettings || { categories: [], skill_level: null }}
          hasDestination={hasDestination}
          onToggle={(enabled) => {
            if (onUpdateBookingTypes) {
              onUpdateBookingTypes({ activities: enabled ? 'on' : 'off' });
            }
            toast(enabled ? 'Activities included' : 'Activities removed');
          }}
          onSaveSettings={(settings) => {
            onUpdateActivitySettings?.(settings);
            toast('Activity preferences saved');
          }}
          onOpenDestination={() => {
            setActivitiesSheetOpen(false);
            setTimeout(() => onOpenSheet?.('destination'), 150);
          }}
        />
      </div>
    );
  }
);
