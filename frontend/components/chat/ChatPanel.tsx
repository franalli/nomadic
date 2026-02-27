'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
// frontend/components/ChatPanel.tsx

import { AnimatePresence, motion } from 'framer-motion';
import { Loader2 } from 'lucide-react';
import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';

import { isBootstrap, isFraming, ITINERARY_STATES } from '@/components/plan/planStateHelpers';
import { UnifiedChipRow } from '@/components/plan/UnifiedChipRow';
import { useToast } from '@/components/ui/toast';
import { useChatEffects } from '@/hooks/useChatEffects';
import { useChatScrolling } from '@/hooks/useChatScrolling';
import { useChatSend } from '@/hooks/useChatSend';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';
import { useChatStore } from '@/state/chatStore';
import { DEFAULT_BOOKING_TYPES } from '@/state/documentStore';
import type {
  ActivitySettings,
  BookingTypes,
  DocumentBranch,
  DocumentTripInputs,
  FlightSettings,
  GraphPlanResponse,
  HotelSettings,
} from '@/types/document';
import type { PlanViewState } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { Tile } from '@/types/tile';

import { ChatInputHandler } from './ChatInputHandler';
import { ChatMessageList } from './ChatMessageList';
import { type VisibleMessage } from './ChatMessageRenderer';
import { ChatModuleSheets } from './ChatModuleSheets';
import { ChatSuggestionBar } from './ChatSuggestionBar';
import { type ActiveStatus, SmartLoader } from './SmartLoader';

// Helper to fix escaped characters from backend
const sanitizeContent = (content: string): string => {
  return content
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\\*/g, '*')
    .replace(/\s*(?:[-–—]\s*)?[Cc]heck\s+(?:the\s+)?right\s+panel[^.!?\n]*[.!]?/g, '')
    .trim();
};

// ─────────────────────────────────────────────────────────────────────────────
// Chat Status Config - maps plan phase to persistent status bar content
// ─────────────────────────────────────────────────────────────────────────────
function getChatStatusConfig(
  planViewState: PlanViewState | undefined,
  planState: string | undefined,
  isGenerating: boolean,
  destination: string | undefined,
  hasDates: boolean,
): { text: string; label: string; indicator: 'blink' | 'spin' | 'pulse' | 'check' } {
  if (isFraming(planViewState) || isGenerating || planState === 'RESOLVING') {
    return { text: 'Building your trip...', label: 'Generating', indicator: 'spin' };
  }
  if (isBootstrap(planViewState)) {
    if (!destination) return { text: 'Where to next?', label: 'Awaiting Input', indicator: 'blink' };
    if (!hasDates) return { text: 'When would you like to go?', label: 'Set Dates', indicator: 'blink' };
    return { text: 'Ready to build your plan', label: 'Generating Plan', indicator: 'blink' };
  }
  if (planViewState && ITINERARY_STATES.has(planViewState)) {
    return { text: 'Itinerary complete', label: 'Ready', indicator: 'check' };
  }
  return { text: 'Your trip is taking shape', label: 'Refine Plan', indicator: 'pulse' };
}

// Stable empty array to avoid new [] identity on every render when not streaming
const EMPTY_VISIBLE_MESSAGES: VisibleMessage[] = [];

// Hoisted Framer Motion animation objects to avoid new object identity on every render
const FADE_INITIAL = { opacity: 0 } as const;
const FADE_ANIMATE = { opacity: 1 } as const;
const FADE_EXIT = { opacity: 0 } as const;
const FADE_TRANSITION = { duration: 0.3, ease: [0.4, 0, 0.2, 1] } as const;

const MESSAGE_BURST_COOLDOWN_MS = 1000;
const GENERATE_BURST_COOLDOWN_MS = 3000;

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
  /** Destination hero image URL — shown as chat panel header in plan mode */
  destinationImageUrl?: string | null;
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
      destination,
      origin,
      dateRange,
      budget,
      hasDestination = false,
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
      destinationImageUrl,
    } = props;

    const isInputDisabledByPlanState = planState === 'RESOLVING';
    const isDesktop = useIsDesktop();
    const { toast } = useToast();

    // Chat store — messages + history
    const messages = useChatStore((s) => s.messages);
    const isLoadingHistory = useChatStore((s) => s.isLoadingHistory);
    const loadHistory = useChatStore((s) => s.loadHistory);
    const filterMessages = useChatStore((s) => s.filterMessages);

    // Local state shared across hooks
    const [isSetupHeaderCollapsed, setIsSetupHeaderCollapsed] = useState(false);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    const [activeStatus, setActiveStatus] = useState<ActiveStatus | null>(null);

    // Module sheet open states
    const [flightsSheetOpen, setFlightsSheetOpen] = useState(false);
    const [staysSheetOpen, setStaysSheetOpen] = useState(false);
    const [activitiesSheetOpen, setActivitiesSheetOpen] = useState(false);

    const panelRef = useRef<HTMLDivElement | null>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);

    // ── Scroll management ──
    const {
      scrollContainerRef,
      bottomSentinelRef,
      scrollToBottom,
      handleScroll,
      scrollPanelIntoView,
    } = useChatScrolling({
      panelRef,
      isDesktop,
      onSetupHeaderCollapse: setIsSetupHeaderCollapsed,
    });

    // ── Send orchestration ──
    const chatSend = useChatSend({
      onPlanResult,
      onGeneratePlanStart,
      onAutoExpandItinerary,
      onUserMessageSubmit,
      selectedBranchId,
      hasBranches,
      setGenerateTriggered,
      setActiveStatus,
      scrollPanelIntoView,
      inputRef,
      toast,
    });

    // ── Side effects ──
    useChatEffects({
      isLoading: chatSend.isLoading,
      isLoadingHistory,
      messages,
      scrollToBottom,
      scrollPanelIntoView,
      inputRef,
      readyToGenerate,
      hasBranches,
      generateTriggered,
      setGenerateTriggered,
      loadHistory,
      filterMessages,
      nodeStatus: chatSend.nodeStatus,
      setActiveStatus,
      autoExpandTimeoutRef: chatSend.autoExpandTimeoutRef,
      focusTimeoutRef: chatSend.focusTimeoutRef,
    });

    // ── Imperative handle ──
    useImperativeHandle(
      ref,
      () => ({
        sendMessage: chatSend.sendMessageCore,
        addAssistantMessage: chatSend.addAssistantMessage,
        stopStreaming: chatSend.handleStopStreaming,
      }),
      [chatSend.sendMessageCore, chatSend.addAssistantMessage, chatSend.handleStopStreaming]
    );

    // ── Effective suggestions ──
    const effectiveSuggestions = useMemo(() => {
      if (chatSend.suggestedResponses.length === 0) return [];
      const seen = new Set<string>();
      const filtered = chatSend.suggestedResponses.filter((s) => {
        const isFieldCTA = /^(set|add|change)\s/i.test(s);
        if (!isFieldCTA) return true;
        const lower = s.toLowerCase();
        if (seen.has(lower)) return false;
        seen.add(lower);
        return true;
      });
      let result = filtered;
      if (isDesktop) {
        result = filtered.filter((s) => s.toLowerCase() !== 'build plan');
      }
      return result;
    }, [chatSend.suggestedResponses, isDesktop]);

    // ── Panel height ──
    const panelHeightClass = fullHeight
      ? 'h-full'
      : !isDesktop
        ? 'h-full'
        : 'min-h-[300px]';

    // ── Visible messages ──
    const streamingMessageId = chatSend.streamingMessageId;
    const stableMessages = useMemo(
      () => messages.filter((m) => m.id !== streamingMessageId),
      [messages, streamingMessageId],
    );
    const visibleStable = useMemo(() => {
      const visible: VisibleMessage[] = [];

      const splitMessageIfNeeded = (m: VisibleMessage): VisibleMessage[] => {
        if (m.role !== 'assistant') return [m];
        const paragraphs = m.content.split(/\n\n+/).filter((p) => p.trim().length > 0);
        if (paragraphs.length > 1) {
          return paragraphs.map((paragraph, idx) => ({
            ...m,
            id: `${m.id}_p${idx}`,
            content: paragraph.trim(),
            _isPartOfSplit: true,
            _isFirstPart: idx === 0,
            _isLastPart: idx === paragraphs.length - 1,
          }));
        }
        const words = m.content.split(/\s+/).filter(Boolean).length;
        const sentences = m.content.split(/(?<=[.!?])\s+(?=[A-Z])/).filter((s) => s.trim());
        if (sentences.length >= 3 && words > 40) {
          const parts = [sentences[0].trim(), sentences.slice(1).join(' ').trim()];
          return parts.map((part, idx) => ({
            ...m,
            id: `${m.id}_p${idx}`,
            content: part,
            _isPartOfSplit: true,
            _isFirstPart: idx === 0,
            _isLastPart: idx === parts.length - 1,
          }));
        }
        return [m];
      };

      for (const message of stableMessages) {
        if (message.role === 'system' || message.displayMode === 'ack_line') continue;
        if (!message.content || message.content.trim().length === 0) continue;
        if (isGenerating && message.id === 'm0') continue;

        const canonicalContent =
          hasBranches && message.id === 'm0' ? 'Edit constraints.' : message.content;
        const sanitized = sanitizeContent(canonicalContent);
        if (!sanitized || sanitized.trim().length === 0) continue;

        const normalized: VisibleMessage = { ...message, content: sanitized };
        const split = splitMessageIfNeeded(normalized);
        visible.push(...split);
      }

      return visible;
    }, [stableMessages, isGenerating, hasBranches]);

    const streamingMessage = useMemo(
      () => messages.find((m) => m.id === streamingMessageId) ?? null,
      [messages, streamingMessageId],
    );

    const streamingVisible = useMemo(() => {
      if (!streamingMessage) return EMPTY_VISIBLE_MESSAGES;
      const sanitized = sanitizeContent(streamingMessage.content);
      if (!sanitized || sanitized.trim().length === 0) return EMPTY_VISIBLE_MESSAGES;
      return [
        {
          ...streamingMessage,
          content: sanitized,
        },
      ];
    }, [streamingMessage]);

    const visibleMessages = useMemo(
      () => [...visibleStable, ...streamingVisible],
      [visibleStable, streamingVisible],
    );

    return (
      <div
        ref={panelRef}
        className={cn(
          'text-foreground flex min-h-0 w-full flex-col gap-4 bg-transparent p-4 transition-[min-height,max-height] duration-300',
          panelHeightClass,
          !isDesktop && 'pb-1',
        )}
      >
        {/* ── DESKTOP: Hero status bar — shrink-0 header for non-bootstrap states ── */}
        {isDesktop && !isBootstrap(planViewState) && (() => {
          const status = getChatStatusConfig(planViewState, planState, isGenerating ?? false, destination, hasDates);
          const showHero = !!(destinationImageUrl && hasDestination);
          return (
            <AnimatePresence mode="wait">
              <motion.div
                key="status-bar"
                initial={FADE_INITIAL}
                animate={FADE_ANIMATE}
                exit={FADE_EXIT}
                transition={FADE_TRANSITION}
                className={cn(
                  'relative z-40 shrink-0',
                  '-mx-4 -mt-4 mb-2',
                  'w-[calc(100%+2rem)]',
                  'overflow-hidden',
                  showHero
                    ? 'h-[120px]'
                    : 'h-14 border-b border-border/80 bg-background/80 backdrop-blur-md',
                )}
              >
                {/* Hero image — only when destination image available */}
                {showHero && (
                  <img
                    src={destinationImageUrl!}
                    alt={destination}
                    className="absolute inset-0 h-full w-full object-cover brightness-90 saturate-[1.1]"
                  />
                )}
                {/* Scrim: bottom half fades hard to panel background, top stays clear */}
                {showHero && (
                  <div className="absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-black/60 to-transparent pointer-events-none" />
                )}
                {!showHero && (
                  <div className="absolute inset-0 z-10 flex items-center gap-2 px-4">
                    {status.indicator === 'spin' ? (
                      <Loader2 className="h-3 w-3 animate-spin text-primary" />
                    ) : status.indicator === 'check' ? null : (
                      <div className={cn(
                        'h-2 w-2 rounded-full bg-primary',
                        status.indicator === 'pulse' && 'animate-pulse',
                      )} />
                    )}
                    <span className="text-sm font-semibold text-foreground">
                      {status.text}
                    </span>
                    <span className={cn(
                      `font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-muted-foreground`,
                      DS.glowClass.dropText,
                    )}>
                      {status.label}
                    </span>
                  </div>
                )}
              </motion.div>
            </AnimatePresence>
          );
        })()}

        {/* ── Scrollable message list ── */}
        {/* Bootstrap hero + chips are passed as scrollHeaderContent so they scroll with messages */}
        <ChatMessageList
          scrollContainerRef={scrollContainerRef}
          bottomSentinelRef={bottomSentinelRef}
          onScroll={handleScroll}
          isLoadingHistory={isLoadingHistory}
          isLoading={chatSend.isLoading}
          visibleMessages={visibleMessages}
          streamingMessageId={chatSend.streamingMessageId}
          lastUserMessage={chatSend.lastUserMessage}
          onRetry={chatSend.sendMessageCore}
          isDesktop={isDesktop}
          planViewState={planViewState}
          isLanding={isDesktop && (isBootstrap(planViewState) || isFraming(planViewState))}
          scrollHeaderContent={isDesktop && isBootstrap(planViewState) && !isSetupHeaderCollapsed ? (() => {
            const status = getChatStatusConfig(planViewState, planState, isGenerating ?? false, destination, hasDates);
            return (
              <>
                {/* Hero banner — scrolls up as messages arrive */}
                <div className="flex flex-col items-center justify-center text-center px-4 pb-4">
                  <h1 className="text-2xl font-semibold tracking-tight text-foreground">
                    {status.text}
                  </h1>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span className={cn(
                      `font-mono ${DS.textSize.nano} uppercase tracking-[0.12em] font-bold text-primary`,
                      DS.glowClass.dropText,
                    )}>
                      {status.label}
                    </span>
                    <div className={cn(
                      'h-1.5 w-1 animate-terminal-blink rounded-sm bg-primary',
                      DS.glowClass.cursor,
                    )} />
                  </div>
                </div>
                {/* Unified Chip Row — scrolls with hero */}
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
                {/* Divider between setup controls and conversation */}
                <div className="mx-auto mb-4 mt-6 w-2/3 border-t border-border/50" />
              </>
            );
          })() : undefined}
        />

        {/* Input area with suggestions — pinned below scroll container */}
        <div className="shrink-0 space-y-4 pb-0 relative z-20">
          {/* Smart Loader: Status line above input - DS Section 19.C */}
          {chatSend.isLoading && activeStatus && visibleMessages[visibleMessages.length - 1]?.role === 'user' && (
            <SmartLoader status={activeStatus} />
          )}
          <ChatSuggestionBar
            effectiveSuggestions={effectiveSuggestions}
            suggestionChips={chatSend.suggestionChips}
            suggestedResponseMeta={chatSend.suggestedResponseMeta}
            isLoading={chatSend.isLoading}
            bookingTypes={bookingTypes}
            onUpdateFlightSettings={onUpdateFlightSettings}
            onUpdateBookingTypes={onUpdateBookingTypes}
            onOpenSheet={onOpenSheet}
            onSendMessage={chatSend.sendMessageCore}
            onOpenFlights={() => setFlightsSheetOpen(true)}
            onOpenStays={() => setStaysSheetOpen(true)}
            onOpenActivities={() => setActivitiesSheetOpen(true)}
            toast={toast}
          />

          {/* Exploration Progress + Action Bar — desktop only (mobile uses MobileChatInput) */}
          {isDesktop && (
            <ChatInputHandler
              input={chatSend.input}
              onInputChange={chatSend.setInput}
              onSubmit={chatSend.handleSubmit}
              onStopStreaming={chatSend.handleStopStreaming}
              isLoading={chatSend.isLoading}
              isInputDisabledByPlanState={isInputDisabledByPlanState}
              hasReceivedFirstToken={chatSend.hasReceivedFirstToken}
              nodeStatus={chatSend.nodeStatus}
              readyToGenerate={readyToGenerate}
              isGenerating={isGenerating}
              hasBranches={hasBranches}
              hasDestination={hasDestination}
              planViewState={planViewState}
              inputRef={inputRef}
            />
          )}
        </div>{/* close input area */}

        {/* Module sheets (flights/stays/activities) */}
        <ChatModuleSheets
          bookingTypes={bookingTypes}
          flightSettings={flightSettings}
          hotelSettings={hotelSettings}
          activitySettings={activitySettings}
          planViewState={planViewState}
          origin={origin}
          hasDestination={hasDestination}
          hasDates={hasDates}
          onUpdateBookingTypes={onUpdateBookingTypes}
          onUpdateFlightSettings={onUpdateFlightSettings}
          onUpdateHotelSettings={onUpdateHotelSettings}
          onUpdateActivitySettings={onUpdateActivitySettings}
          onOpenSheet={onOpenSheet}
          sendMessageCore={chatSend.sendMessageCore}
          toast={toast}
          flightsSheetOpen={flightsSheetOpen}
          setFlightsSheetOpen={setFlightsSheetOpen}
          staysSheetOpen={staysSheetOpen}
          setStaysSheetOpen={setStaysSheetOpen}
          activitiesSheetOpen={activitiesSheetOpen}
          setActivitiesSheetOpen={setActivitiesSheetOpen}
        />
      </div>
    );
  }
);
