'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { forwardRef, useImperativeHandle } from 'react';

import { cn } from '@/lib/utils';

import { ErrorBoundary } from '../ui/ErrorBoundary';
import { ChatInputHandler } from './ChatInputHandler';
import { ChatMessageList } from './ChatMessageList';
import { ChatModuleSheets } from './ChatModuleSheets';
import type { ChatPanelHandle, ChatPanelProps } from './ChatPanel.types';
import { ActiveLoaderSection, buildScrollHeaderContent } from './ChatPanelContentParts';
import { shouldShowBootstrapHero, shouldUseLandingChatLayout } from './chatPanelLayout';
import { ChatStatusHeader } from './ChatStatusHeader';
import { ChatSuggestionBar } from './ChatSuggestionBar';
import { useChatPanelController } from './useChatPanelController';

export type { ChatPanelHandle, ChatPanelProps } from './ChatPanel.types';

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel(
  props,
  ref
) {
  const {
    hasBranches, isGenerating, readyToGenerate, planState,
    destination, origin, dateRange, budget,
    hasDestination = false, hasDates = false,
    tripInputs, bookingTypes, flightSettings, hotelSettings, activitySettings,
    onUpdateBookingTypes, onUpdateFlightSettings, onUpdateHotelSettings,
    planViewState, isFraming: isFramingProp,
    onOpenSheet, destinationImageUrl, onConfirmReset,
  } = props;

  const {
    activeStatus, scrollContainerRef, bottomSentinelRef, chatSend, effectiveSuggestions,
    handleScroll, isDesktop, inputRef, toast, isLoadingHistory, isInputDisabledByPlanState,
    isRegenerating, isSetupHeaderCollapsed, openModuleSheet, panelHeightClass, panelRef,
    setOpenModuleSheet, visibleMessages,
  } = useChatPanelController(props);

  useImperativeHandle(
    ref,
    () => ({
      sendMessage: chatSend.sendMessageCore,
      addAssistantMessage: chatSend.addAssistantMessage,
      stopStreaming: chatSend.handleStopStreaming,
    }),
    [chatSend.addAssistantMessage, chatSend.handleStopStreaming, chatSend.sendMessageCore]
  );

  const useLandingChatLayout = shouldUseLandingChatLayout({
    isDesktop,
    planViewState,
    isFraming: isFramingProp,
    isGenerating: isGenerating ?? false,
  });
  const showBootstrapHero = shouldShowBootstrapHero({
    isDesktop,
    planViewState,
    isFraming: isFramingProp,
    isGenerating: isGenerating ?? false,
    isSetupHeaderCollapsed,
  });
  const shouldTightenInitialLoadingGap =
    isDesktop &&
    chatSend.isLoading &&
    visibleMessages.length === 1 &&
    visibleMessages[0]?.role === 'user' &&
    panelHeightClass === 'min-h-[300px]';
  const effectivePanelHeightClass = shouldTightenInitialLoadingGap
    ? 'min-h-[220px]'
    : panelHeightClass;

  return (
    <ErrorBoundary label="chat">
      <div
        ref={panelRef}
        className={cn(
          'text-zinc-900 dark:text-white flex min-h-0 w-full flex-col gap-4 bg-transparent p-4 transition-[min-height,max-height] duration-300',
          effectivePanelHeightClass,
          !isDesktop && 'pb-1'
        )}
      >
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
          isLanding={useLandingChatLayout}
          scrollHeaderContent={buildScrollHeaderContent({
            showBootstrapHero,
            planViewState,
            planState,
            isGenerating: isGenerating ?? false,
            isFraming: isFramingProp,
            destination,
            origin,
            hasDates,
            dateRange,
            budget,
            tripInputs,
            bookingTypes,
            flightSettings,
            hotelSettings,
            activitySettings,
            onOpenSheet,
            onOpenModuleSheet: setOpenModuleSheet,
          })}
        />

        <div className="relative z-20 shrink-0 space-y-4 pb-0">
          <ActiveLoaderSection
            isRegenerating={isRegenerating}
            isLoading={chatSend.isLoading}
            activeStatus={activeStatus}
            visibleMessages={visibleMessages}
          />
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
              messageCount={visibleMessages.length}
              planViewState={planViewState ?? undefined}
              inputRef={inputRef}
            />
          )}
        </div>

        <ChatModuleSheets
          bookingTypes={bookingTypes}
          flightSettings={flightSettings}
          hotelSettings={hotelSettings}
          activitySettings={activitySettings}
          origin={origin}
          hasDestination={hasDestination}
          hasDates={hasDates}
          onUpdateBookingTypes={onUpdateBookingTypes}
          onUpdateFlightSettings={onUpdateFlightSettings}
          onUpdateHotelSettings={onUpdateHotelSettings}
          onOpenSheet={onOpenSheet}
          sendMessageCore={chatSend.sendMessageCore}
          toast={toast}
          openModuleSheet={openModuleSheet}
          setOpenModuleSheet={setOpenModuleSheet}
        />
      </div>
    </ErrorBoundary>
  );
});
