'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
// frontend/components/ChatPanel.tsx

import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react';

import { isBootstrap } from '@/components/plan/planStateHelpers';
import { useToast } from '@/components/ui/toast';
import { useChatEffects } from '@/hooks/useChatEffects';
import { useChatMessagePipeline } from '@/hooks/useChatMessagePipeline';
import { useChatScrolling } from '@/hooks/useChatScrolling';
import { useChatSend } from '@/hooks/useChatSend';
import { useIsDesktop } from '@/hooks/useIsDesktop';
import { cn } from '@/lib/utils';
import { useChatStore } from '@/state/chatStore';
import { useDocumentStore } from '@/state/documentStore';
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

import { ErrorBoundary } from '../ui/ErrorBoundary';
import { ChatBootstrapHero } from './ChatBootstrapHero';
import { ChatInputHandler } from './ChatInputHandler';
import { ChatMessageList } from './ChatMessageList';
import { ChatModuleSheets } from './ChatModuleSheets';
import { ChatStatusHeader } from './ChatStatusHeader';
import { ChatSuggestionBar } from './ChatSuggestionBar';
import { type ActiveStatus, SmartLoader } from './SmartLoader';

// Re-exports for backward compatibility (moved to chatMessageProcessing.ts / suggestion-actions.ts)
export { getSendBurstGuardReason } from './chatMessageProcessing';
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
  planViewState?: PlanViewState | null;
  /** UI loading signal: backend state not yet received but generation is active. */
  isFraming?: boolean;
  /** Shared sheet opener - opens trip input sheets at common parent level */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Destination hero image URL — shown as chat panel header in plan mode */
  destinationImageUrl?: string | null;
  /**
   * Callback when user submits a message (before backend responds).
   * Used for optimistic UI - detect topics and show placeholder AgentCards.
   */
  onUserMessageSubmit?: (message: string) => void;
  /** Callback to confirm and execute a session reset (e.g. from suggestion chip) */
  onConfirmReset?: () => void;
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
      isFraming: isFramingProp,
      onOpenSheet,
      onUserMessageSubmit,
      destinationImageUrl,
      onConfirmReset,
    } = props;

    const isInputDisabledByPlanState = planState === 'RESOLVING';
    const isDesktop = useIsDesktop();
    const { toast } = useToast();
    const isRegenerating = useDocumentStore((s) => s.isRegenerating);

    // Chat store — messages + history
    const messages = useChatStore((s) => s.messages);
    const isLoadingHistory = useChatStore((s) => s.isLoadingHistory);
    const loadHistory = useChatStore((s) => s.loadHistory);
    const filterMessages = useChatStore((s) => s.filterMessages);

    // Local state shared across hooks
    const [isSetupHeaderCollapsed, setIsSetupHeaderCollapsed] = useState(false);
    const [generateTriggered, setGenerateTriggered] = useState(false);
    const [activeStatus, setActiveStatus] = useState<ActiveStatus | null>(null);

    // Module sheet open state — at most one sheet open at a time
    const [openModuleSheet, setOpenModuleSheet] = useState<'flights' | 'stays' | 'activities' | null>(null);

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
      scrollToBottom,
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
    const visibleMessages = useChatMessagePipeline(
      messages, chatSend.streamingMessageId, isGenerating ?? false, hasBranches ?? false,
    );

    return (
      <ErrorBoundary label="chat">
      <div
        ref={panelRef}
        className={cn(
          'text-foreground flex min-h-0 w-full flex-col gap-4 bg-transparent p-4 transition-[min-height,max-height] duration-300',
          panelHeightClass,
          !isDesktop && 'pb-1',
        )}
      >
        {/* ── DESKTOP: Hero status bar — shrink-0 header for non-bootstrap states ── */}
        {isDesktop && (
          <ChatStatusHeader
            planViewState={planViewState}
            isFraming={isFramingProp}
            planState={planState}
            isGenerating={isGenerating ?? false}
            destination={destination}
            hasDates={hasDates}
            hasDestination={hasDestination}
            destinationImageUrl={destinationImageUrl}
          />
        )}

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
          planViewState={planViewState ?? undefined}
          isLanding={isDesktop && (isBootstrap(planViewState) || !!isFramingProp)}
          scrollHeaderContent={isDesktop && isBootstrap(planViewState) && !isSetupHeaderCollapsed ? (
            <ChatBootstrapHero
              planViewState={planViewState} planState={planState}
              isGenerating={isGenerating ?? false} isFraming={isFramingProp}
              destination={destination} origin={origin} hasDates={hasDates}
              dateRange={dateRange} budget={budget} tripInputs={tripInputs}
              bookingTypes={bookingTypes} flightSettings={flightSettings}
              hotelSettings={hotelSettings} activitySettings={activitySettings}
              onOpenSheet={onOpenSheet} onOpenModuleSheet={setOpenModuleSheet}
            />
          ) : undefined}
        />

        {/* Input area with suggestions — pinned below scroll container */}
        <div className="shrink-0 space-y-4 pb-0 relative z-20">
          {/* Smart Loader: Status line above input - DS Section 19.C */}
          {isRegenerating ? (
            /* Regeneration loader — settings change triggers rebuild (single step, no multi-step sequence) */
            <SmartLoader status={{ label: 'REBUILDING ITINERARY', icon_key: 'calendar' }} />
          ) : chatSend.isLoading && activeStatus && visibleMessages[visibleMessages.length - 1]?.role === 'user' ? (
            <SmartLoader status={activeStatus} />
          ) : null}
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
            onConfirmReset={onConfirmReset}
            onOpenFlights={() => setOpenModuleSheet('flights')}
            onOpenStays={() => setOpenModuleSheet('stays')}
            onOpenActivities={() => setOpenModuleSheet('activities')}
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
              isRegenerating={isRegenerating}
              readyToGenerate={readyToGenerate}
              isGenerating={isGenerating}
              hasBranches={hasBranches}
              hasDestination={hasDestination}
              planViewState={planViewState ?? undefined}
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
          planViewState={planViewState ?? undefined}
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
          openModuleSheet={openModuleSheet}
          setOpenModuleSheet={setOpenModuleSheet}
        />
      </div>
      </ErrorBoundary>
    );
  }
);
