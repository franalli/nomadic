'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
// frontend/components/ChatPanel.tsx

import { AnimatePresence, motion } from 'framer-motion';
import { Check, Loader2 } from 'lucide-react';
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useShallow } from 'zustand/react/shallow';

import { isBootstrap, isFraming } from '@/components/plan/planStateHelpers';
import { ActivitiesSheet } from '@/components/plan/sheets/ActivitiesSheet';
import { FlightsSheet } from '@/components/plan/sheets/FlightsSheet';
import { StaysSheet } from '@/components/plan/sheets/StaysSheet';
import { UnifiedChipRow } from '@/components/plan/UnifiedChipRow';
import { useToast } from '@/components/ui/toast';
import { useActionLoader } from '@/hooks/useActionLoader';
import { useChatSse } from '@/hooks/useChatSse';
import { useDelayedLoader } from '@/hooks/useDelayedLoader';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { type streamGraphPlan } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { GENERATE_PLAN_TRIGGER, useChatStore } from '@/state/chatStore';
import { DEFAULT_BOOKING_TYPES, useDocumentStore } from '@/state/documentStore';
import type { AckUpdate, ChatMessage } from '@/types/chat';
import {
  type ActivitySettings,
  type BookingTypes,
  type DocumentBranch,
  type DocumentTripInputs,
  type FlightSettings,
  type GraphPlanResponse,
  type HotelSettings,
  isBookingEnabled,
  type SuggestionChip,
  type SuggestionChipMeta,
} from '@/types/document';
import type { TriggerContext } from '@/types/loader';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { ChatInputHandler } from './ChatInputHandler';
import { ChatMessageList } from './ChatMessageList';
import { type VisibleMessage } from './ChatMessageRenderer';
import { ChatSuggestionBar } from './ChatSuggestionBar';
// HoldToDeleteButton removed for demo - re-enable post-launch
// import { HoldToDeleteButton } from './HoldToDeleteButton';
import { MobileSetupCollapsedHeader } from './MobileSetupCollapsedHeader';
// TripStatusBar is mobile-only (rendered in SplitLayoutView shared slot)
// NodeProgress removed - replaced by Live Logic Status Pill above input
import { type ActiveStatus, SmartLoader } from './SmartLoader';

// Helper to fix escaped characters from backend
// Converts literal escape sequences to actual characters for proper markdown rendering
const sanitizeContent = (content: string): string => {
  return content
    .replace(/\\n/g, '\n')  // Replace literal \n with actual newlines
    .replace(/\\t/g, '\t')  // Replace literal \t with actual tabs
    .replace(/\\\*/g, '*')  // Unescape asterisks for markdown bold/italic
    // Strip "right panel" references — no right panel on mobile, redundant on desktop
    .replace(/\s*(?:[-–—]\s*)?[Cc]heck\s+(?:the\s+)?right\s+panel[^.!?\n]*[.!]?/g, '')
    .trim();
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

// ─────────────────────────────────────────────────────────────────────────────
// Chat Status Config - maps plan phase to persistent status bar content
// ─────────────────────────────────────────────────────────────────────────────
function getChatStatusConfig(
  planViewState: PlanViewState | undefined,
  planState: string | undefined,
  isGenerating: boolean,
  destination: string | undefined,
  dateRange: string | undefined,
): { text: string; label: string; indicator: 'blink' | 'spin' | 'pulse' | 'check' } {
  // Active generation / resolving (check BEFORE bootstrap — S1_FRAMING normalizes to P0_MINIMAL)
  if (isFraming(planViewState) || isGenerating || planState === 'RESOLVING') {
    return { text: 'Building your trip...', label: 'Generating', indicator: 'spin' };
  }

  // S0/P0: Setup phase — progressive prompts
  if (isBootstrap(planViewState)) {
    if (!destination) return { text: 'Where to next?', label: 'Awaiting Input', indicator: 'blink' };
    if (!dateRange) return { text: 'When would you like to go?', label: 'Set Dates', indicator: 'blink' };
    return { text: 'Ready to build your plan', label: 'Generating Plan', indicator: 'blink' };
  }

  // Itinerary complete
  if (planViewState && ['S3_ITINERARY_READY', 'S3_EDITING', 'P3_FINALIZED', 'P3_EDITING'].includes(planViewState)) {
    return { text: 'Itinerary complete', label: 'Ready', indicator: 'check' };
  }

  // Plan ready, refinement phase (S2, P0, P1, P2, and fallback)
  return { text: 'Your trip is taking shape', label: 'Refine Plan', indicator: 'pulse' };
}

const MESSAGE_BURST_COOLDOWN_MS = 1000;
const GENERATE_BURST_COOLDOWN_MS = 3000;
function buildSendRequestId(now: number): string {
  return `req_${now}_${Math.random().toString(36).slice(2, 8)}`;
}

type SendBurstGuardParams = {
  isGenerateTrigger: boolean;
  isLoading: boolean;
  now: number;
  lastMessageSentAt: number;
  lastGenerateClickedAt: number;
};

export function getSendBurstGuardReason(params: SendBurstGuardParams): string | null {
  const {
    isGenerateTrigger,
    isLoading,
    now,
    lastMessageSentAt,
    lastGenerateClickedAt,
  } = params;
  if (isGenerateTrigger) {
    if (isLoading) return 'Plan generation already in progress';
    if (now - lastGenerateClickedAt < GENERATE_BURST_COOLDOWN_MS) {
      return 'Please wait a moment before generating again';
    }
    return null;
  }
  if (isLoading) return 'loading';
  if (now - lastMessageSentAt < MESSAGE_BURST_COOLDOWN_MS) {
    return "You're sending too quickly";
  }
  return null;
}

// Re-export for backward compatibility (moved to suggestion-actions.ts)
export { handleSuggestionTriggerAction } from './suggestion-actions';


interface ChatPanelProps {
  selectedBranchId: string | null;
  /** Called when generate plan trigger is sent (before API call) */
  onGeneratePlanStart?: () => void;
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
  // CTA gating flags
  /** Whether user has set a destination */
  hasDestination?: boolean;
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
  /** Update booking types callback */
  onUpdateBookingTypes?: (settings: Partial<BookingTypes>) => void;
  /** Update flight settings callback */
  onUpdateFlightSettings?: (settings: Partial<FlightSettings>) => void;
  /** Update hotel settings callback */
  onUpdateHotelSettings?: (settings: Partial<HotelSettings>) => void;
  /** Update activity settings callback */
  onUpdateActivitySettings?: (settings: Partial<ActivitySettings>) => void;
  /** Plan view state for CTA gating (hide generate after S2) */
  planViewState?: PlanViewState;
  /** Shared sheet opener - opens trip input sheets at common parent level */
  onOpenSheet?: (sheet: SheetType) => void;
  /**
   * Callback when user submits a message (before backend responds).
   * Used for optimistic UI - detect topics and show placeholder AgentCards.
   */
  onUserMessageSubmit?: (message: string) => void;
}

export interface ChatPanelHandle {
  sendMessage: (message: string) => Promise<void>;
  addAssistantMessage: (message: string) => void;
  stopStreaming: () => void;
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
      planState,
      // Onboarding chips props - click handlers are internal
      destination,
      origin,
      dateRange,
      budget,
      // CTA gating flags
      hasDestination = false,
      // Optional Refinements Section props
      hasDates = false,
      tripInputs,
      bookingTypes,
      flightSettings,
      hotelSettings,
      activitySettings,
      onUpdateBookingTypes,
      onUpdateFlightSettings,
      onUpdateHotelSettings,
      onUpdateActivitySettings,
      planViewState,
      onOpenSheet,
      onUserMessageSubmit,
    } = props;

    // Derive input disabled state from planState (RESOLVING = disabled)
    const isInputDisabledByPlanState = planState === 'RESOLVING';

    // Use chat store for messages, history loading, and session state
    const {
      messages,
      addMessage,
      updateMessage,
      appendToMessage,
      updateMessageId,
      filterMessages,
      isLoadingHistory,
      loadHistory,
      sessionState,
      setSessionState,
    } = useChatStore(useShallow((state) => ({
      messages: state.messages,
      addMessage: state.addMessage,
      updateMessage: state.updateMessage,
      appendToMessage: state.appendToMessage,
      updateMessageId: state.updateMessageId,
      filterMessages: state.filterMessages,
      isLoadingHistory: state.isLoadingHistory,
      loadHistory: state.loadHistory,
      sessionState: state.sessionState,
      setSessionState: state.setSessionState,
    })));

    // Get desktop mode to determine if right panel with "Build Plan" button is visible
    const isDesktop = useIsDesktop();

    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
    const [hasReceivedFirstToken, setHasReceivedFirstToken] = useState(false);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    const [readyMessageShown, setReadyMessageShown] = useState(false);
    const [suggestedResponses, setSuggestedResponses] = useState<string[]>([]);
    const [suggestedResponseMeta, setSuggestedResponseMeta] = useState<SuggestionChipMeta[]>([]);
    const [suggestionChips, setSuggestionChips] = useState<SuggestionChip[]>([]);
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
    const autoExpandTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const focusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const sheetOpenTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const abortStreamRef = useRef<(() => void) | null>(null);
    // SYNC GUARD: Prevent duplicate message sends (React StrictMode safe)
    const isSendingRef = useRef(false);
    const lastMessageSentAtRef = useRef(0);
    const lastGenerateClickedAtRef = useRef(0);
    // Track previous specialist types and tile types for structural change detection
    // IMPORTANT: Use specialist_type (not title) for consistent comparison
    const prevSpecialistTypesRef = useRef<Set<string>>(new Set());
    const prevTileTypesRef = useRef<Set<string>>(new Set());
    // Track previous trip inputs for change detection (dates, travelers, budget, origin)
    const prevTripInputsRef = useRef<{
      start_date: string | null;
      end_date: string | null;
      adults: number | null;
      children: number | null;
      budget: number | null;
      origin: string | null;
    } | null>(null);

    // SSE streaming hook — owns the streamGraphPlan call and all callbacks
    const { executeStream } = useChatSse(
      {
        abortStreamRef,
        isSendingRef,
        autoExpandTimeoutRef,
        prevSpecialistTypesRef,
        prevTileTypesRef,
        prevTripInputsRef,
        lastUserMsgIdRef,
      },
      {
        setHasReceivedFirstToken,
        setNodeStatus,
        setStreamingMessageId,
        setTriggerContext,
        setSuggestedResponses,
        setSuggestedResponseMeta,
        setSuggestionChips,
        setIsLoading,
        setSessionState,
        appendToMessage,
        updateMessage,
        updateMessageId,
        filterMessages,
        onPlanResult,
        onAutoExpandItinerary,
      }
    );

    // Compute effective suggestions: use backend suggestions if available
    const effectiveSuggestions = useMemo(() => {
      if (suggestedResponses.length === 0) {
        return [];
      }

      // Dedupe: keep first occurrence of each field-type CTA (e.g., "Set budget")
      // to avoid multiple identical buttons
      const seen = new Set<string>();
      const filtered = suggestedResponses.filter((s) => {
        const isFieldCTA = /^(set|add|change)\s/i.test(s);
        if (!isFieldCTA) return true;
        const lower = s.toLowerCase();
        if (seen.has(lower)) return false;
        seen.add(lower);
        return true;
      });

      // On desktop, filter out "Build Plan" chip since the right panel has that CTA
      // Keep one primary CTA at a time to avoid competing buttons
      let result = filtered;
      if (isDesktop) {
        result = filtered.filter((s) => s.toLowerCase() !== 'build plan');
      }

      return result;
    }, [suggestedResponses, isDesktop]);



    // Dynamic height — mobile fills parent (docked input), desktop grows naturally
    const panelHeightClass = fullHeight
      ? 'h-full'
      : !isDesktop
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

    // Cleanup timeouts on unmount
    useEffect(() => {
      return () => {
        if (scrollTimeoutRef.current) {
          clearTimeout(scrollTimeoutRef.current);
        }
        if (autoExpandTimeoutRef.current) {
          clearTimeout(autoExpandTimeoutRef.current);
        }
        if (focusTimeoutRef.current) {
          clearTimeout(focusTimeoutRef.current);
        }
        if (sheetOpenTimeoutRef.current) {
          clearTimeout(sheetOpenTimeoutRef.current);
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
        if (!trimmed) {
          debugLog('[ChatPanel] ⏭️ Skipping - empty message');
          return;
        }

        // SYNC GUARD: Prevent duplicate sends (React StrictMode safe)
        if (isSendingRef.current) {
          debugLog('[ChatPanel] ⏭️ Skipping - already sending (ref guard)');
          return;
        }

        // MUTATION GATE: Wait for in-flight mutations (fill-day, drag-drop) to settle
        // so the graph reads the latest document version. Chat input stays enabled.
        if (useDocumentStore.getState().hasPendingMutations()) {
          const maxWait = 10_000;
          const poll = 100;
          const start = Date.now();
          while (useDocumentStore.getState().hasPendingMutations() && Date.now() - start < maxWait) {
            await new Promise(r => setTimeout(r, poll));
          }
        }

        // Check for generate trigger FIRST (before isLoading guard)
        const isGenerateTrigger = trimmed === GENERATE_PLAN_TRIGGER || trimmed.toLowerCase() === 'build plan';
        const now = Date.now();
        const requestId = buildSendRequestId(now);

        // DEBUG: Log all sendMessage calls
        debugLog('[ChatPanel] sendMessageCore called', {
          message: trimmed.slice(0, 50),
          isGenerateTrigger,
          isLoading,
          request_id: requestId,
          destination: useDocumentStore.getState().document?.trip_inputs?.destination,
        });

        const guardReason = getSendBurstGuardReason({
          isGenerateTrigger,
          isLoading,
          now,
          lastMessageSentAt: lastMessageSentAtRef.current,
          lastGenerateClickedAt: lastGenerateClickedAtRef.current,
        });
        if (guardReason) {
          if (guardReason !== 'loading') {
            toast(guardReason);
          } else {
            debugLog('[ChatPanel] ⏭️ Skipping - loading');
          }
          return;
        }
        if (isGenerateTrigger) {
          lastGenerateClickedAtRef.current = now;
        } else {
          lastMessageSentAtRef.current = now;
        }

        if (isLoading) {
          debugLog('[ChatPanel] ⏭️ Skipping - loading');
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
        setSuggestedResponseMeta([]);
        setSuggestionChips([]);
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

        // Flush any pending pill/settings PATCH to the backend document before
        // the graph starts. Without this, the graph reads a stale document that
        // doesn't have the user's latest pill selections (race condition).
        await useDocumentStore.getState().ensureSettingsFlushed({
          requestId,
          sendCycleId: requestId,
        });

        // Use SSE streaming for real-time token display
        const currentTripInputs = useDocumentStore.getState().document?.trip_inputs;

        // Capture trip inputs BEFORE API call for change detection
        // Same pattern as structural change detection (lines 1056-1087)
        prevTripInputsRef.current = currentTripInputs ? {
          start_date: currentTripInputs.start_date ?? null,
          end_date: currentTripInputs.end_date ?? null,
          adults: currentTripInputs.adults ?? null,
          children: currentTripInputs.children ?? null,
          budget: currentTripInputs.budget ?? null,
          origin: currentTripInputs.origin ?? null,
        } : null;

        const body: Parameters<typeof streamGraphPlan>[0] = {
          message: trimmed,
          session_state: sessionState ?? undefined,
          // Pass suggestion_clicked when user clicked a suggestion chip
          // This enables LQA suggestion echo in the backend
          suggestion_clicked: options?.suggestionClicked,
          // CRITICAL: Always pass current frontend trip_inputs so the backend
          // graph sees the latest settings (activity_settings, hotel_settings, etc.)
          // Without this, session_state carries stale defaults that override document values
          trip_inputs: currentTripInputs ?? undefined,
        };

        // DEBUG: Log API payload for regeneration triggers
        if (isGenerateTrigger) {
          debugLog('[ChatPanel] 📤 Sending GENERATE_PLAN_TRIGGER to API', {
            destination: body.trip_inputs?.destination,
            start_date: body.trip_inputs?.start_date,
            end_date: body.trip_inputs?.end_date,
            hasTripInputs: !!body.trip_inputs,
          });
        }

        // Delegate the SSE stream execution to the useChatSse hook
        await executeStream({
          body,
          streamingMsgId,
          isSilentPlanGeneration,
          selectedBranchId,
          triggerContext,
          delayedLoader,
          actionLoader,
        });
      },
      [isLoading, onPlanResult, onGeneratePlanStart, selectedBranchId, sessionState, addMessage, appendToMessage, filterMessages, updateMessageId, updateMessage, setSessionState, delayedLoader, actionLoader, triggerContext, hasBranches, onUserMessageSubmit, onAutoExpandItinerary, toast, executeStream]
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

    useImperativeHandle(
      ref,
      () => ({
        sendMessage: sendMessageCore,
        addAssistantMessage,
        stopStreaming: handleStopStreaming,
      }),
      [sendMessageCore, addAssistantMessage, handleStopStreaming]
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
      focusTimeoutRef.current = setTimeout(() => inputRef.current?.focus(), 0);
      await sendMessageCore(trimmed);
    }

    // Simple render - no content-based filters, just show all non-empty messages
    // During generation, hide the initial welcome message to keep focus on the "All details collected" message
    // After branches are ready, replace the welcome message with a prompt to refine the trip
    // Split assistant messages by paragraph breaks into separate bubbles for better readability
    const visibleMessages = messages
      .filter((m) => {
        // Always show system messages and messages with special displayMode
        if (m.role === 'system' || m.displayMode === 'ack_line') {
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
      .flatMap((m): VisibleMessage[] => {
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
        className={cn(
          'text-foreground flex min-h-0 w-full flex-col gap-4 transition-[min-height,max-height] duration-300 bg-transparent p-4',
          panelHeightClass,
          !isDesktop && 'pb-1',
        )}
      >
        {/* ── DESKTOP: Persistent status header (all states) ── */}
        {isDesktop && (() => {
          const status = getChatStatusConfig(planViewState, planState, isGenerating ?? false, destination, dateRange);
          return (
            <AnimatePresence mode="wait">
              {isBootstrap(planViewState) ? (
                // S0/P0: Full hero banner (collapses on scroll)
                isSetupHeaderCollapsed ? (
                  <MobileSetupCollapsedHeader
                    key="collapsed-header"
                    tripInputs={tripInputs}
                    dateRange={dateRange}
                    onExpand={() => {
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
                    <div
                      className="absolute inset-0 animate-topo-drift topo-contour-mask-350 opacity-[0.12] dark:opacity-[0.08]"
                    >
                      <div className="absolute inset-0 bg-black dark:bg-white" />
                    </div>
                    <div className="relative z-10 flex flex-col items-center justify-center text-center px-4 py-6">
                      <h1 className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-white">
                        {status.text}
                      </h1>
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <span className={`font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-zinc-950 dark:text-emerald-500 dark:${DS.glowClass.dropText}`}>
                          {status.label}
                        </span>
                        <div className={`w-1 h-1.5 bg-zinc-950 dark:bg-emerald-500 animate-terminal-blink rounded-sm dark:${DS.glowClass.cursor}`} />
                      </div>
                    </div>
                  </motion.div>
                )
              ) : (
                // Post-S0: Compact glassmorphism status bar
                <motion.div
                  key="status-bar"
                  initial={{ opacity: 0, y: -20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -20 }}
                  transition={{ duration: 0.2, ease: 'easeOut' }}
                  className={cn(
                    'z-40 shrink-0',
                    '-mx-4 -mt-4 mb-2',
                    'w-[calc(100%+2rem)]',
                    'h-14 px-4',
                    'bg-white dark:bg-zinc-900',
                    'border-b border-zinc-200 dark:border-white/5',
                    'flex items-center',
                  )}
                >
                  <div className="flex items-center gap-2">
                    {/* Status indicator */}
                    {status.indicator === 'spin' ? (
                      <Loader2 className="w-3 h-3 animate-spin text-emerald-500" />
                    ) : status.indicator === 'check' ? (
                      <Check className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <div className={cn(
                        'w-2 h-2 rounded-full bg-emerald-500',
                        status.indicator === 'pulse' && 'animate-pulse',
                      )} />
                    )}
                    {/* Status text */}
                    <span className="text-sm font-semibold text-zinc-900 dark:text-white">
                      {status.text}
                    </span>
                    {/* Label badge */}
                    <span className={`font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-zinc-500 dark:text-emerald-500 dark:${DS.glowClass.dropText}`}>
                      {status.label}
                    </span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          );
        })()}

        {/* ── DESKTOP: Unified Chip Row (S0 only) ── */}
        {isDesktop && isBootstrap(planViewState) && !isSetupHeaderCollapsed && (
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
            destinationLocked={!!destination}
          />
        )}

        {/* ── Scrollable message list ── */}
        <ChatMessageList
          scrollContainerRef={scrollContainerRef}
          bottomSentinelRef={bottomSentinelRef}
          onScroll={handleScroll}
          isLoadingHistory={isLoadingHistory}
          isLoading={isLoading}
          visibleMessages={visibleMessages}
          streamingMessageId={streamingMessageId}
          lastUserMessage={lastUserMessage}
          onRetry={sendMessageCore}
          isDesktop={isDesktop}
          planViewState={planViewState}
        />

        {/* Input area with suggestions — pinned below scroll container */}
        <div className="shrink-0 space-y-4 pb-0">
          {/* Smart Loader: Status line above input - DS Section 19.C */}
          {isLoading && activeStatus && visibleMessages[visibleMessages.length - 1]?.role === 'user' && (
            <SmartLoader status={activeStatus} />
          )}
          <ChatSuggestionBar
            effectiveSuggestions={effectiveSuggestions}
            suggestionChips={suggestionChips}
            suggestedResponseMeta={suggestedResponseMeta}
            isLoading={isLoading}
            bookingTypes={bookingTypes}
            onUpdateFlightSettings={onUpdateFlightSettings}
            onUpdateBookingTypes={onUpdateBookingTypes}
            onOpenSheet={onOpenSheet}
            onSendMessage={sendMessageCore}
            onOpenFlights={() => setFlightsSheetOpen(true)}
            onOpenStays={() => setStaysSheetOpen(true)}
            onOpenActivities={() => setActivitiesSheetOpen(true)}
            toast={toast}
          />

          {/* Exploration Progress + Action Bar — desktop only (mobile uses MobileChatInput) */}
          {isDesktop && (
            <ChatInputHandler
              input={input}
              onInputChange={setInput}
              onSubmit={handleSubmit}
              onStopStreaming={handleStopStreaming}
              isLoading={isLoading}
              isInputDisabledByPlanState={isInputDisabledByPlanState}
              hasReceivedFirstToken={hasReceivedFirstToken}
              nodeStatus={nodeStatus}
              readyToGenerate={readyToGenerate}
              isGenerating={isGenerating}
              hasBranches={hasBranches}
              hasDestination={hasDestination}
              planViewState={planViewState}
              inputRef={inputRef}
            />
          )}
        </div>{/* close input area */}

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
            sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('origin'), 150);
          }}
          onOpenDestination={() => {
            setFlightsSheetOpen(false);
            sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('destination'), 150);
          }}
          onOpenDates={() => {
            setFlightsSheetOpen(false);
            sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('dates'), 150);
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
            // Trigger plan regeneration if plan is active
            const isActive = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
              planViewState ?? ''
            );
            if (isActive) {
              const updates: AckUpdate[] = [];
              if (settings.min_stars) updates.push({ field: 'hotels', to: `${settings.min_stars}+ stars` });
              if (updates.length > 0) {
                addMessage({ id: `sys_ack_${Date.now()}`, role: 'system', content: '', displayMode: 'ack_line', ackStatus: 'applied', ackUpdates: updates });
              }
              sendMessageCore(GENERATE_PLAN_TRIGGER);
            }
          }}
          onOpenDestination={() => {
            setStaysSheetOpen(false);
            sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('destination'), 150);
          }}
          onOpenDates={() => {
            setStaysSheetOpen(false);
            sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('dates'), 150);
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
            // Capture prev state before update for ack diff
            const prevDayPrefs = activitySettings?.day_preferences || {};
            const prevCats = new Set(activitySettings?.categories || []);
            onUpdateActivitySettings?.(settings);
            toast('Activity preferences saved');
            // Trigger plan regeneration if plan is active
            const isActive = ['S2_STRATEGY_READY', 'S3_ITINERARY_READY', 'S3_EDITING'].includes(
              planViewState ?? ''
            );
            if (isActive) {
              const newDayPrefs = settings.day_preferences || {};
              const newCats = new Set(settings.categories || []);
              const updates: AckUpdate[] = [];
              // Diff categories: show added/removed activities
              for (const cat of newCats) {
                if (!prevCats.has(cat)) {
                  updates.push({ field: cat, to: 'added' });
                }
              }
              for (const cat of prevCats) {
                if (!newCats.has(cat)) {
                  updates.push({ field: cat, to: 'removed' });
                }
              }
              // Diff day_preferences: show "Diving 3 → 5 days"
              for (const [topic, newVal] of Object.entries(newDayPrefs)) {
                const prevVal = prevDayPrefs[topic];
                if (prevVal !== undefined && prevVal !== newVal) {
                  updates.push({ field: topic, to: `${newVal} days`, from_value: `${prevVal} days` });
                } else if (prevVal === undefined) {
                  updates.push({ field: topic, to: `${newVal} days` });
                }
              }
              if (updates.length > 0) {
                addMessage({ id: `sys_ack_${Date.now()}`, role: 'system', content: '', displayMode: 'ack_line', ackStatus: 'applied', ackUpdates: updates });
              }
              sendMessageCore(GENERATE_PLAN_TRIGGER);
            }
          }}
          onOpenDestination={() => {
            setActivitiesSheetOpen(false);
            sheetOpenTimeoutRef.current = setTimeout(() => onOpenSheet?.('destination'), 150);
          }}
        />
      </div>
    );
  }
);
