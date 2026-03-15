'use client';
/* eslint no-unused-vars: ["error", { "args": "none" }] */

import { forwardRef, useImperativeHandle } from 'react';

import { isBootstrap } from '@/components/plan/planStateHelpers';
import { cn } from '@/lib/utils';

import { ErrorBoundary } from '../ui/ErrorBoundary';
import { ChatBootstrapHero } from './ChatBootstrapHero';
import { ChatInputHandler } from './ChatInputHandler';
import { ChatMessageList } from './ChatMessageList';
import { ChatModuleSheets } from './ChatModuleSheets';
import type { ChatPanelHandle, ChatPanelProps } from './ChatPanel.types';
import { ChatStatusHeader } from './ChatStatusHeader';
import { ChatSuggestionBar } from './ChatSuggestionBar';
import { SmartLoader } from './SmartLoader';
import { useChatPanelController } from './useChatPanelController';

export type { ChatPanelHandle, ChatPanelProps } from './ChatPanel.types';

export const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(function ChatPanel(
  props,
  ref
) {
  const {
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
    destinationImageUrl,
    onConfirmReset,
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

  return (
    <ErrorBoundary label="chat">
      <div
        ref={panelRef}
        className={cn(
          'text-zinc-900 dark:text-white flex min-h-0 w-full flex-col gap-4 bg-transparent p-4 transition-[min-height,max-height] duration-300',
          panelHeightClass,
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
          isLanding={isDesktop && (isBootstrap(planViewState) || !!isFramingProp)}
          scrollHeaderContent={
            isDesktop && isBootstrap(planViewState) && !isSetupHeaderCollapsed ? (
              <ChatBootstrapHero
                planViewState={planViewState}
                planState={planState}
                isGenerating={isGenerating ?? false}
                isFraming={isFramingProp}
                destination={destination}
                origin={origin}
                hasDates={hasDates}
                dateRange={dateRange}
                budget={budget}
                tripInputs={tripInputs}
                bookingTypes={bookingTypes}
                flightSettings={flightSettings}
                hotelSettings={hotelSettings}
                activitySettings={activitySettings}
                onOpenSheet={onOpenSheet}
                onOpenModuleSheet={setOpenModuleSheet}
              />
            ) : undefined
          }
        />

        <div className="relative z-20 shrink-0 space-y-4 pb-0">
          {isRegenerating ? (
            <SmartLoader
              status={{ label: 'REBUILDING ITINERARY', icon_key: 'calendar' }}
            />
          ) : chatSend.isLoading &&
            activeStatus &&
            visibleMessages[visibleMessages.length - 1]?.role === 'user' ? (
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
        </div>

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
});
